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
        read_only_fields = [
            "id",
            "created_at",
            "potential_payout",
            "status",
            "bet_definition_title",
            "user",
            "team",
            "probability_distribution",
        ]

    def validate(self, data):
        # Validate bet definition is active
        bet_definition = data.get("bet_definition")
        if not bet_definition.is_active:
            raise serializers.ValidationError("Cannot place bet on inactive bet definition")

        # Get the latest probability distribution
        latest_distribution = bet_definition.latest_probability_distribution
        if not latest_distribution:
            raise serializers.ValidationError("No probability distribution available for this bet definition")

        # Set the probability distribution to the latest one
        data["probability_distribution"] = latest_distribution

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
        team = request.user.current_team if request else None

        # Set the user and team from the request
        if user and "user" not in validated_data:
            validated_data["user"] = user
        if team and "team" not in validated_data:
            validated_data["team"] = team

        # Calculate potential payout
        bet_definition = validated_data.get("bet_definition")
        prob_dist = validated_data.get("probability_distribution")
        amount = validated_data.get("amount")
        predicted_value = validated_data.get("predicted_value")

        if bet_definition and prob_dist and amount and predicted_value is not None:
            if isinstance(predicted_value, dict) and "value" in predicted_value:
                value_to_check = predicted_value["value"]
            else:
                value_to_check = predicted_value

            payout_multiplier = prob_dist.get_payout_for_value(float(value_to_check))
            potential_payout = float(amount) * payout_multiplier
            validated_data["potential_payout"] = potential_payout

        # Create the bet and handle the transaction in a single atomic transaction
        with transaction.atomic():
            try:
                # Create the bet
                bet = super().create(validated_data)

                # Deduct the amount from the user's wallet
                if user:
                    try:
                        Wallet.place_bet(user, bet)
                    except Exception as e:
                        raise serializers.ValidationError(f"Failed to process bet transaction: {str(e)}")

                return bet
            except Exception:
                raise


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

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.request.user.current_team.id).order_by("-created_at")

    def perform_create(self, serializer, **kwargs):
        # Set the team to the current team
        serializer.save(team_id=self.request.user.current_team.id)

        # Get the created bet definition
        bet_definition = serializer.instance

        # Create a probability distribution for the bet definition
        self._create_demo_distribution(bet_definition, **kwargs)

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

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()

        # Filter by bet definition if provided
        bet_definition_id = self.request.query_params.get("bet_definition")
        if bet_definition_id:
            queryset = queryset.filter(bet_definition_id=bet_definition_id)

        return queryset.filter(bet_definition__team_id=self.request.user.current_team.id).order_by("-created_at")


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

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception:
            raise

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.request.user.current_team.id, user=self.request.user).order_by(
            "-created_at"
        )

    def perform_create(self, serializer):
        team = self.request.user.current_team
        serializer.save(user=self.request.user, team=team)

    @action(detail=False, methods=["get"])
    def by_definition(self, request, **kwargs):
        """
        Get all bets for a specific bet definition.
        """
        bet_definition_id = request.query_params.get("bet_definition_id")
        if not bet_definition_id:
            return Response({"error": "bet_definition_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            bets = Bet.objects.filter(
                team_id=request.user.current_team.id, bet_definition_id=bet_definition_id
            ).order_by("-created_at")
            serializer = BetSerializer(bets, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"])
    def my_bets(self, request, **kwargs):
        """
        Get user's bets for a specific bet definition.
        """
        bet_definition_id = request.query_params.get("bet_definition_id")
        if not bet_definition_id:
            return Response({"error": "bet_definition_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            bets = Bet.objects.filter(
                team_id=request.user.current_team.id, bet_definition_id=bet_definition_id, user=request.user
            ).order_by("-created_at")
            serializer = BetSerializer(bets, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def estimate(self, request, **kwargs):
        """
        Estimate potential payout for a bet without creating it.
        """
        bet_definition_id = request.data.get("bet_definition")
        amount = request.data.get("amount")
        predicted_value = request.data.get("predicted_value")

        if not bet_definition_id or not amount or predicted_value is None:
            return Response({"error": "Missing required parameters"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Get the bet definition
            bet_definition = BetDefinition.objects.get(id=bet_definition_id, team_id=request.user.current_team.id)

            # Get the latest probability distribution
            prob_dist = bet_definition.latest_probability_distribution

            if not prob_dist:
                return Response({"error": "No probability distribution available"}, status=status.HTTP_400_BAD_REQUEST)

            # Calculate potential payout
            potential_payout = Bet.calculate_potential_payout(bet_definition, prob_dist, float(amount), predicted_value)

        except BetDefinition.DoesNotExist:
            return Response({"error": "Bet definition not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "amount": amount,
                "predicted_value": predicted_value,
                "potential_payout": potential_payout,
            }
        )


class LeaderboardEntrySerializer(serializers.Serializer):
    user_email = serializers.CharField()
    balance = serializers.FloatField()
    win_rate = serializers.FloatField(required=False)
    total_bets = serializers.IntegerField(required=False)
    total_wins = serializers.IntegerField(required=False)
    total_volume = serializers.FloatField(required=False)


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

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset()
        return queryset.filter(team_id=str(self.request.user.current_team.id), user=self.request.user).order_by(
            "-created_at"
        )

    @action(detail=False, methods=["get"])
    def wallet_balance(self, request, **kwargs):
        """
        Get the current wallet balance for the user in this team.
        """
        balance = Wallet.get_balance(request.user, str(request.user.current_team.id))
        return Response({"balance": balance})

    @action(detail=False, methods=["get"])
    def leaderboard(self, request, **kwargs):
        """
        Get the leaderboard for the current team.
        Supports different leaderboard types: 'balance', 'win_rate', 'volume'
        """
        leaderboard_type = request.query_params.get("type", "balance")
        limit = int(request.query_params.get("limit", 10))

        # Get all users in the current team
        from posthog.models.user import User

        team_id = str(request.user.current_team.id)

        if leaderboard_type == "balance":
            # Get users with their wallet balances
            users_with_balances = []
            team_users = User.objects.filter(
                organization_membership__organization=self.request.user.current_organization
            )

            for user in team_users:
                balance = Wallet.get_balance(user, team_id)
                if balance > 0:  # Only include users with positive balances
                    users_with_balances.append({"user_email": user.email, "balance": balance})

            # Sort by balance descending
            leaderboard = sorted(users_with_balances, key=lambda x: x["balance"], reverse=True)[:limit]

        elif leaderboard_type == "win_rate":
            # Calculate win rate for each user
            users_with_stats = []
            team_users = User.objects.filter(
                organization_membership__organization=self.request.user.current_organization
            )

            for user in team_users:
                # Get all bets for this user
                bets = Bet.objects.filter(user=user, team_id=team_id)
                total_bets = bets.count()

                if total_bets > 0:
                    total_wins = bets.filter(status=Bet.Status.WON).count()
                    win_rate = (total_wins / total_bets) * 100 if total_bets > 0 else 0

                    users_with_stats.append(
                        {
                            "user_email": user.email,
                            "win_rate": win_rate,
                            "total_bets": total_bets,
                            "total_wins": total_wins,
                        }
                    )

            # Sort by win rate descending
            leaderboard = sorted(users_with_stats, key=lambda x: x["win_rate"], reverse=True)[:limit]

        elif leaderboard_type == "volume":
            # Calculate trading volume for each user
            users_with_volume = []
            team_users = User.objects.filter(
                organization_membership__organization=self.request.user.current_organization
            )

            for user in team_users:
                # Sum the amount of all bet_place transactions
                transactions = TransactionLedger.objects.filter(
                    user=user, team_id=team_id, transaction_type="bet_place", source="wallet"
                )

                total_volume = sum(t.amount for t in transactions)

                if total_volume > 0:
                    users_with_volume.append(
                        {
                            "user_email": user.email,
                            "total_volume": total_volume,
                            "balance": None,
                            "win_rate": None,
                            "total_bets": None,
                            "total_wins": None,
                        }
                    )

            # Sort by volume descending
            leaderboard = sorted(users_with_volume, key=lambda x: x["total_volume"], reverse=True)[:limit]

        else:
            return Response(
                {"error": f"Invalid leaderboard type: {leaderboard_type}"}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = LeaderboardEntrySerializer(leaderboard, many=True)
        return Response(serializer.data)


class OnboardingViewSet(viewsets.ViewSet):
    """
    ViewSet for onboarding users to the betting feature.
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def initialize(self, request, **kwargs):
        """
        Initialize a user's wallet with the onboarding bonus.
        """
        user = request.user
        team_id = str(request.user.current_team.id)

        # Check if user already has transactions
        if TransactionLedger.objects.filter(user=user, team_id=team_id).exists():
            return Response({"error": "User already onboarded"}, status=status.HTTP_400_BAD_REQUEST)

        # Add onboarding bonus
        Wallet.add_onboarding_bonus(user, team_id)

        return Response(
            {"status": "success", "message": "Onboarding complete", "balance": Wallet.get_balance(user, team_id)}
        )
