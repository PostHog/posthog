from rest_framework import viewsets, mixins, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from posthog.models.betting import (
    BetDefinition,
    ProbabilityDistribution,
    Bet,
    TransactionLedger,
    Wallet,
)


class BetDefinitionSerializer(serializers.ModelSerializer):
    latest_distribution = serializers.SerializerMethodField()

    class Meta:
        model = BetDefinition
        fields = [
            "id",
            "team",
            "type",
            "bet_parameters",
            "closing_date",
            "status",
            "probability_distribution_interval",
            "title",
            "description",
            "created_at",
            "latest_distribution",
            "final_value",
        ]
        read_only_fields = ["id", "created_at", "latest_distribution", "team"]

    def get_latest_distribution(self, obj):
        latest = obj.latest_probability_distribution
        if latest:
            return {
                "id": str(latest.id),
                "created_at": latest.created_at,
                "buckets": latest.buckets,
            }
        return None

    def validate(self, data):
        if data.get("closing_date") and data["closing_date"] < timezone.now():
            raise serializers.ValidationError("Closing date must be in the future")
        return data


class ProbabilityDistributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProbabilityDistribution
        fields = ["id", "bet_definition", "distribution_data", "created_at"]
        read_only_fields = ["id", "created_at"]


class BetSerializer(serializers.ModelSerializer):
    bet_definition_title = serializers.CharField(source="bet_definition.title", read_only=True)

    class Meta:
        model = Bet
        fields = [
            "id",
            "bet_definition",
            "bet_definition_title",
            "probability_distribution",
            "user",
            "team",
            "amount",
            "predicted_value",
            "potential_payout",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "potential_payout", "status", "bet_definition_title", "user", "team"]

    def validate(self, data):
        # Validate bet definition is active
        bet_definition = data.get("bet_definition")
        if not bet_definition.is_active:
            raise serializers.ValidationError("Cannot place bet on inactive bet definition")

        # Validate probability distribution belongs to bet definition
        prob_dist = data.get("probability_distribution")
        if prob_dist and prob_dist.bet_definition.id != bet_definition.id:
            raise serializers.ValidationError("Probability distribution does not belong to this bet definition")

        # Validate user has sufficient funds
        request = self.context.get("request")
        if request and request.user:
            user = request.user
            team = request.user.current_team
            team_id = str(team.id)
            amount = data.get("amount")

            if amount and not Wallet.has_sufficient_funds(user, team_id, amount):
                raise serializers.ValidationError("Insufficient funds")

        return data

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user if request else None

        # Set the user from the request
        if user and "user" not in validated_data:
            validated_data["user"] = user

        # Calculate potential payout
        bet_definition = validated_data.get("bet_definition")
        prob_dist = validated_data.get("probability_distribution")
        amount = validated_data.get("amount")
        predicted_value = validated_data.get("predicted_value")

        if bet_definition and prob_dist and amount and predicted_value is not None:
            # Get payout multiplier
            if isinstance(predicted_value, dict) and "value" in predicted_value:
                value_to_check = predicted_value["value"]
            else:
                value_to_check = predicted_value

            payout_multiplier = prob_dist.get_payout_for_value(float(value_to_check))
            potential_payout = float(amount) * payout_multiplier
            validated_data["potential_payout"] = potential_payout

        # Create the bet
        bet = super().create(validated_data)

        # Deduct the amount from the user's wallet
        if user:
            Wallet.place_bet(user, bet)

        return bet


class TransactionLedgerSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = TransactionLedger
        fields = [
            "id",
            "user",
            "user_email",
            "team_id",
            "entry_type",
            "transaction_type",
            "amount",
            "reference_id",
            "description",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "user", "user_email"]


class BetDefinitionViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for bet definitions.
    """

    permission_classes = [IsAuthenticated]
    queryset = BetDefinition.objects.all()
    serializer_class = BetDefinitionSerializer

    @property
    def team_id(self):
        return self.kwargs.get("parent_lookup_team_id") or self.kwargs.get("team_id")

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def perform_create(self, serializer, **kwargs):
        # Set the team to the current team
        team = self.request.user.current_team
        serializer.save(team=team)

        # Create an initial probability distribution if interval is specified
        bet_definition = serializer.instance
        if bet_definition.probability_distribution_interval > 0:
            self._create_demo_distribution(bet_definition)

    def _create_demo_distribution(self, bet_definition, **kwargs):
        """
        Create a demo probability distribution for the bet definition.
        In a real implementation, this would be replaced with actual data.
        """
        # Create a simple distribution with 3 buckets
        distribution_data = [
            {"value": 100, "probability": 0.2},
            {"value": 200, "probability": 0.5},
            {"value": 300, "probability": 0.3},
        ]

        ProbabilityDistribution.objects.create(
            bet_definition=bet_definition,
            distribution_data=distribution_data,
        )

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None, **kwargs):
        """
        Settle a bet definition with the final value.
        """
        bet_definition = self.get_object()

        # Check if bet definition can be settled
        if bet_definition.status != BetDefinition.Status.ACTIVE:
            return Response(
                {"error": "Cannot settle a bet definition that is not active"}, status=status.HTTP_400_BAD_REQUEST
            )

        final_value = request.data.get("final_value")
        if final_value is None:
            return Response({"error": "final_value is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Settle the bet definition and all related bets
        with transaction.atomic():
            bet_definition.settle(final_value)

            # Get all active bets for this definition
            bets = Bet.objects.filter(bet_definition=bet_definition, status=Bet.Status.ACTIVE)

            # Settle each bet
            for bet in bets:
                bet.settle(final_value)

        return Response({"status": "success", "message": "Bet definition settled", "final_value": final_value})


class ProbabilityDistributionViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for probability distributions.
    """

    permission_classes = [IsAuthenticated]
    queryset = ProbabilityDistribution.objects.all()
    serializer_class = ProbabilityDistributionSerializer

    @property
    def team_id(self):
        return self.kwargs.get("parent_lookup_team_id") or self.kwargs.get("team_id")

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()

        # Filter by bet definition if provided
        bet_definition_id = self.request.query_params.get("bet_definition")
        if bet_definition_id:
            queryset = queryset.filter(bet_definition_id=bet_definition_id)

        return queryset.filter(bet_definition__team_id=self.team_id).order_by("-created_at")


class BetViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for bets.
    """

    permission_classes = [IsAuthenticated]
    queryset = Bet.objects.all()
    serializer_class = BetSerializer

    @property
    def team_id(self):
        return self.kwargs.get("parent_lookup_team_id") or self.kwargs.get("team_id")

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id, user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        team = self.request.user.current_team
        serializer.save(user=self.request.user, team=team)

    @action(detail=False, methods=["post"])
    def estimate(self, request, **kwargs):
        """
        Estimate potential payout for a bet without creating it.
        """

        bet_definition_id = request.data.get("bet_definition")
        predicted_value = request.data.get("predicted_value")
        amount = request.data.get("amount")

        if not all([bet_definition_id, predicted_value is not None, amount is not None]):
            return Response(
                {"error": "bet_definition, predicted_value, and amount are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            bet_definition = BetDefinition.objects.get(id=bet_definition_id, team_id=self.team_id)
        except BetDefinition.DoesNotExist:
            return Response({"error": "Bet definition not found"}, status=status.HTTP_404_NOT_FOUND)

        if not bet_definition.is_active:
            return Response(
                {"error": "Cannot place bet on inactive bet definition"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Get latest probability distribution
        prob_dist = bet_definition.latest_probability_distribution
        if not prob_dist:
            return Response({"error": "No probability distribution available"}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate potential payout
        if isinstance(predicted_value, dict) and "value" in predicted_value:
            value_to_check = predicted_value["value"]
        else:
            value_to_check = predicted_value

        payout_multiplier = prob_dist.get_payout_for_value(float(value_to_check))
        potential_payout = float(amount) * payout_multiplier

        return Response(
            {
                "amount": amount,
                "predicted_value": predicted_value,
                "payout_multiplier": payout_multiplier,
                "potential_payout": potential_payout,
            }
        )


class TransactionViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for transaction ledger entries.
    """

    permission_classes = [IsAuthenticated]
    queryset = TransactionLedger.objects.all()
    serializer_class = TransactionLedgerSerializer

    @property
    def team_id(self):
        return self.kwargs.get("parent_lookup_team_id") or self.kwargs.get("team_id")

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id, user=self.request.user).order_by("-created_at")

    @action(detail=False, methods=["get"])
    def wallet_balance(self, request, **kwargs):
        """
        Get the current wallet balance for the user in this team.
        """
        balance = Wallet.get_balance(request.user, str(self.team_id))
        return Response({"balance": balance})


class OnboardingViewSet(viewsets.ViewSet):
    """
    ViewSet for onboarding users to the betting feature.
    """

    permission_classes = [IsAuthenticated]

    @property
    def team_id(self):
        return self.kwargs.get("parent_lookup_team_id") or self.kwargs.get("team_id")

    @action(detail=False, methods=["post"])
    def initialize(self, request, **kwargs):
        """
        Initialize a user's wallet with the onboarding bonus.
        """
        user = request.user
        team_id = str(self.team_id)

        # Check if user already has transactions
        if TransactionLedger.objects.filter(user=user, team_id=team_id).exists():
            return Response({"error": "User already onboarded"}, status=status.HTTP_400_BAD_REQUEST)

        # Add onboarding bonus
        Wallet.add_onboarding_bonus(user, team_id)

        return Response(
            {"status": "success", "message": "Onboarding complete", "balance": Wallet.get_balance(user, team_id)}
        )
