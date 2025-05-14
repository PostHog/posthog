from django.db import models
from django.utils import timezone
from django.db.models import Sum, Q
from posthog.models.team import Team
from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from typing import Dict, List, Optional, Tuple, Any, Literal
import uuid
import json


class BetDefinition(UUIDModel, CreatedMetaFields):
    """
    Defines a bet that users can place wagers on.
    """
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    type = models.CharField(max_length=50, default="pageviews")
    query_params = models.JSONField(default=dict)  # Stores query parameters like URL pattern, etc.
    closing_date = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("closed", "Closed"),
            ("settled", "Settled"),
            ("cancelled", "Cancelled"),
        ],
        default="active",
    )
    probability_distribution_interval = models.IntegerField(default=600)  # In seconds, default 10 minutes
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    final_value = models.FloatField(null=True, blank=True)  # The actual final value when bet is settled

    def __str__(self) -> str:
        return f"{self.title} ({self.type})"

    __repr__ = sane_repr("team", "type", "title", "status")

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.closing_date > timezone.now()
    
    @property
    def latest_probability_distribution(self) -> Optional["ProbabilityDistribution"]:
        return self.probability_distributions.order_by("-created_at").first()
    
    def settle(self, final_value: float) -> None:
        """Settle the bet with the final value and update all related bets."""
        self.final_value = final_value
        self.status = "settled"
        self.save(update_fields=["final_value", "status"])
        
        # Update all related bets
        for bet in self.bets.all():
            bet.settle(final_value)


class ProbabilityDistribution(UUIDModel, CreatedMetaFields):
    """
    Represents the probability distribution for a bet definition at a specific point in time.
    """
    bet_definition = models.ForeignKey(
        BetDefinition, on_delete=models.CASCADE, related_name="probability_distributions"
    )
    distribution_data = models.JSONField()  # List of {value: float, probability: float} objects
    
    def __str__(self) -> str:
        return f"Distribution for {self.bet_definition.title} at {self.created_at}"

    __repr__ = sane_repr("bet_definition", "created_at")
    
    @property
    def buckets(self) -> List[Dict[str, float]]:
        """Returns the distribution data as a list of buckets."""
        return self.distribution_data
    
    def get_payout_for_value(self, value: float) -> float:
        """
        Calculate the payout multiplier for a bet on a specific value.
        """
        for bucket in self.buckets:
            if bucket["value"] == value:
                # Payout is inverse of probability (minus house edge)
                house_edge = 0.05  # 5% house edge
                return (1 / bucket["probability"]) * (1 - house_edge)
        return 0.0


class Bet(UUIDModel, CreatedMetaFields):
    """
    Represents a bet placed by a user.
    """
    bet_definition = models.ForeignKey(BetDefinition, on_delete=models.CASCADE, related_name="bets")
    probability_distribution = models.ForeignKey(
        ProbabilityDistribution, on_delete=models.CASCADE, related_name="bets"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    predicted_value = models.FloatField()  # The value the user is betting on
    potential_payout = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("won", "Won"),
            ("lost", "Lost"),
            ("cancelled", "Cancelled"),
        ],
        default="active",
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    
    def __str__(self) -> str:
        return f"Bet on {self.bet_definition.title} - {self.amount}"

    __repr__ = sane_repr("bet_definition", "amount", "status")
    
    def settle(self, final_value: float) -> None:
        """
        Settle the bet based on the final value.
        """
        # Simple exact match for now - could be expanded to ranges
        if self.predicted_value == final_value:
            self.status = "won"
            # Create winning transaction
            TransactionLedger.objects.create_transaction(
                team=self.team,
                transaction_type="bet_win",
                amount=self.potential_payout,
                reference_id=str(self.id),
                description=f"Won bet on {self.bet_definition.title}"
            )
        else:
            self.status = "lost"
        
        self.save(update_fields=["status"])


class TransactionLedgerManager(models.Manager):
    def create_transaction(
        self, 
        team: Team, 
        transaction_type: str, 
        amount: float, 
        reference_id: str = None,
        description: str = ""
    ) -> Tuple["TransactionLedger", "TransactionLedger"]:
        """
        Create a double-entry bookkeeping transaction.
        Returns a tuple of (debit_entry, credit_entry)
        """
        reference_id = reference_id or str(uuid.uuid4())
        
        # Create debit entry (user's wallet)
        debit_entry = self.create(
            team=team,
            entry_type="debit",
            transaction_type=transaction_type,
            amount=amount,
            reference_id=reference_id,
            description=description
        )
        
        # Create credit entry (system account)
        credit_entry = self.create(
            team=team,
            entry_type="credit",
            transaction_type=transaction_type,
            amount=amount,
            reference_id=reference_id,
            description=description
        )
        
        return debit_entry, credit_entry
    
    def get_wallet_balance(self, team: Team) -> float:
        """
        Calculate the wallet balance for a team.
        """
        debits = self.filter(team=team, entry_type="debit").aggregate(total=Sum("amount"))["total"] or 0
        credits = self.filter(team=team, entry_type="credit").aggregate(total=Sum("amount"))["total"] or 0
        return debits - credits


class TransactionLedger(UUIDModel, CreatedMetaFields):
    """
    Double-entry bookkeeping ledger for tracking all financial transactions.
    """
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    entry_type = models.CharField(
        max_length=10, 
        choices=[("debit", "Debit"), ("credit", "Credit")]
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=[
            ("deposit", "Deposit"),
            ("withdrawal", "Withdrawal"),
            ("bet_place", "Bet Placement"),
            ("bet_win", "Bet Win"),
            ("onboarding", "Onboarding Bonus"),
        ]
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference_id = models.CharField(max_length=100)  # Used to link related transactions
    description = models.TextField(blank=True)
    
    objects = TransactionLedgerManager()
    
    def __str__(self) -> str:
        return f"{self.entry_type.capitalize()} - {self.amount} - {self.transaction_type}"

    __repr__ = sane_repr("team", "entry_type", "transaction_type", "amount")


class Wallet:
    """
    Utility class for wallet operations.
    Not a database model, but provides methods for wallet operations.
    """
    @staticmethod
    def get_balance(team: Team) -> float:
        """Get the current wallet balance for a team."""
        return TransactionLedger.objects.get_wallet_balance(team)
    
    @staticmethod
    def add_onboarding_bonus(team: Team, amount: float = 1000.0) -> Tuple[TransactionLedger, TransactionLedger]:
        """Add the initial onboarding bonus to a team's wallet."""
        return TransactionLedger.objects.create_transaction(
            team=team,
            transaction_type="onboarding",
            amount=amount,
            description="Initial onboarding bonus"
        )
    
    @staticmethod
    def place_bet(team: Team, bet: Bet) -> Tuple[TransactionLedger, TransactionLedger]:
        """Deduct the bet amount from the wallet."""
        return TransactionLedger.objects.create_transaction(
            team=team,
            transaction_type="bet_place",
            amount=bet.amount,
            reference_id=str(bet.id),
            description=f"Bet on {bet.bet_definition.title}"
        )
