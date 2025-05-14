from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from posthog.models.betting import (
    BetDefinition,
    ProbabilityDistribution,
    Bet,
    TransactionLedger,
    Wallet,
)
from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from typing import Any, Dict, List, Optional, Type
import json
from datetime import datetime, timedelta
import random  # For demo probability distributions


class BettingSerializer:
    """
    Container class for all betting-related serializers.
    """
    
    class BetDefinitionSerializer(StructuredViewSetMixin):
        def get_serializer_class(self):
            from rest_framework import serializers
            
            class Serializer(serializers.ModelSerializer):
                latest_distribution = serializers.SerializerMethodField()
                
                class Meta:
                    model = BetDefinition
                    fields = [
                        "id",
                        "team",
                        "type",
                        "query_params",
                        "closing_date",
                        "status",
                        "probability_distribution_interval",
                        "title",
                        "description",
                        "created_at",
                        "latest_distribution",
                    ]
                    read_only_fields = ["id", "created_at", "latest_distribution"]
                
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
            
            return Serializer
    
    class ProbabilityDistributionSerializer(StructuredViewSetMixin):
        def get_serializer_class(self):
            from rest_framework import serializers
            
            class Serializer(serializers.ModelSerializer):
                class Meta:
                    model = ProbabilityDistribution
                    fields = ["id", "bet_definition", "distribution_data", "created_at"]
                    read_only_fields = ["id", "created_at"]
            
            return Serializer
    
    class BetSerializer(StructuredViewSetMixin):
        def get_serializer_class(self):
            from rest_framework import serializers
            
            class Serializer(serializers.ModelSerializer):
                bet_definition_title = serializers.CharField(source="bet_definition.title", read_only=True)
                
                class Meta:
                    model = Bet
                    fields = [
                        "id",
                        "bet_definition",
                        "bet_definition_title",
                        "probability_distribution",
                        "amount",
                        "predicted_value",
                        "potential_payout",
                        "status",
                        "created_at",
                    ]
                    read_only_fields = ["id", "created_at", "potential_payout", "status", "bet_definition_title"]
                
                def validate(self, data):
                    # Ensure bet definition is active
                    bet_definition = data.get("bet_definition")
                    if bet_definition and not bet_definition.is_active:
                        raise serializers.ValidationError("Cannot place bet on inactive bet definition")
                    
                    # Ensure probability distribution belongs to bet definition
                    prob_dist = data.get("probability_distribution")
                    if prob_dist and prob_dist.bet_definition.id != bet_definition.id:
                        raise serializers.ValidationError("Probability distribution must belong to the bet definition")
                    
                    # Validate user has enough balance
                    request = self.context.get("request")
                    if request and hasattr(request, "user") and hasattr(request.user, "team"):
                        team = request.user.team
                        amount = data.get("amount", 0)
                        balance = Wallet.get_balance(team)
                        if amount > balance:
                            raise serializers.ValidationError(f"Insufficient balance. Current balance: {balance}")
                    
                    return data
                
                def create(self, validated_data):
                    # Calculate potential payout
                    prob_dist = validated_data.get("probability_distribution")
                    predicted_value = validated_data.get("predicted_value")
                    amount = validated_data.get("amount")
                    
                    payout_multiplier = prob_dist.get_payout_for_value(predicted_value)
                    potential_payout = float(amount) * payout_multiplier
                    
                    # Add team to validated data
                    request = self.context.get("request")
                    if request and hasattr(request, "user") and hasattr(request.user, "team"):
                        validated_data["team"] = request.user.team
                    
                    # Create bet with calculated potential payout
                    validated_data["potential_payout"] = potential_payout
                    bet = super().create(validated_data)
                    
                    # Create transaction for bet placement
                    Wallet.place_bet(bet.team, bet)
                    
                    return bet
            
            return Serializer
    
    class TransactionLedgerSerializer(StructuredViewSetMixin):
        def get_serializer_class(self):
            from rest_framework import serializers
            
            class Serializer(serializers.ModelSerializer):
                class Meta:
                    model = TransactionLedger
                    fields = [
                        "id",
                        "team",
                        "entry_type",
                        "transaction_type",
                        "amount",
                        "reference_id",
                        "description",
                        "created_at",
                    ]
                    read_only_fields = ["id", "created_at"]
            
            return Serializer


class BetDefinitionViewSet(
    BettingSerializer.BetDefinitionSerializer,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for bet definitions.
    """
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    queryset = BetDefinition.objects.all()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id).order_by("-created_at")
    
    def perform_create(self, serializer):
        bet_definition = serializer.save(team_id=self.team_id)
        
        # Create initial probability distribution
        self._create_probability_distribution(bet_definition)
        
        return bet_definition
    
    def _create_probability_distribution(self, bet_definition):
        """Create a probability distribution for the bet definition."""
        # In a real implementation, this would calculate probabilities based on historical data
        # For now, we'll create a simple mock distribution
        
        if bet_definition.type == "pageviews":
            # Create buckets for pageview counts
            buckets = []
            
            # Example: Create 10 buckets with random probabilities
            base_value = 100  # Base pageview count
            total_prob = 0
            
            for i in range(10):
                value = base_value + (i * 10)  # 100, 110, 120, etc.
                
                # Assign probabilities - higher in the middle, lower at extremes
                if i < 5:
                    prob = 0.05 + (i * 0.03)
                else:
                    prob = 0.05 + ((9 - i) * 0.03)
                
                total_prob += prob
                buckets.append({"value": value, "probability": prob})
            
            # Normalize probabilities to sum to 1
            for bucket in buckets:
                bucket["probability"] = bucket["probability"] / total_prob
            
            # Create the probability distribution
            ProbabilityDistribution.objects.create(
                bet_definition=bet_definition,
                distribution_data=buckets
            )
    
    @action(detail=True, methods=["post"])
    def settle(self, request, **kwargs):
        """Settle a bet definition with the final value."""
        bet_definition = self.get_object()
        
        if bet_definition.status != "active":
            return Response(
                {"error": "Only active bet definitions can be settled"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        final_value = request.data.get("final_value")
        if final_value is None:
            return Response(
                {"error": "Final value is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            bet_definition.settle(float(final_value))
        
        return Response({"status": "Bet definition settled successfully"})


class BetViewSet(
    BettingSerializer.BetSerializer,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for bets.
    """
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    queryset = Bet.objects.all()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id).order_by("-created_at")
    
    @action(detail=False, methods=["post"])
    def estimate(self, request):
        """
        Estimate potential payout for a bet without creating it.
        """
        bet_definition_id = request.data.get("bet_definition")
        predicted_value = request.data.get("predicted_value")
        amount = request.data.get("amount")
        
        if not all([bet_definition_id, predicted_value is not None, amount is not None]):
            return Response(
                {"error": "bet_definition, predicted_value, and amount are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            bet_definition = BetDefinition.objects.get(id=bet_definition_id, team_id=self.team_id)
        except BetDefinition.DoesNotExist:
            return Response(
                {"error": "Bet definition not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not bet_definition.is_active:
            return Response(
                {"error": "Cannot place bet on inactive bet definition"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get latest probability distribution
        prob_dist = bet_definition.latest_probability_distribution
        if not prob_dist:
            return Response(
                {"error": "No probability distribution available"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Calculate potential payout
        payout_multiplier = prob_dist.get_payout_for_value(float(predicted_value))
        potential_payout = float(amount) * payout_multiplier
        
        return Response({
            "amount": amount,
            "predicted_value": predicted_value,
            "payout_multiplier": payout_multiplier,
            "potential_payout": potential_payout,
        })


class TransactionViewSet(
    BettingSerializer.TransactionLedgerSerializer,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for transaction ledger entries.
    """
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    queryset = TransactionLedger.objects.all()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(team_id=self.team_id).order_by("-created_at")
    
    @action(detail=False, methods=["get"])
    def wallet_balance(self, request):
        """
        Get the current wallet balance for the team.
        """
        balance = Wallet.get_balance(request.user.team)
        return Response({"balance": balance})


class OnboardingViewSet(viewsets.ViewSet):
    """
    ViewSet for onboarding users to the betting feature.
    """
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    
    @action(detail=False, methods=["post"])
    def initialize(self, request):
        """
        Initialize a user's wallet with the onboarding bonus.
        """
        team = request.user.team
        
        # Check if user already has transactions
        if TransactionLedger.objects.filter(team=team).exists():
            return Response(
                {"error": "User already onboarded"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add onboarding bonus
        Wallet.add_onboarding_bonus(team)
        
        return Response({
            "status": "success",
            "message": "Onboarding complete",
            "balance": Wallet.get_balance(team)
        })
