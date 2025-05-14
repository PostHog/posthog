from django.db import models
from django.utils import timezone
from django.db.models import Sum
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from typing import Optional
import uuid


class BetDefinition(UUIDModel, CreatedMetaFields):
    """
    Defines a bet that users can place wagers on.
    """

    class BetType(models.TextChoices):
        PAGEVIEWS = "pageviews", "Page Views"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"
        SETTLED = "settled", "Settled"
        CANCELLED = "cancelled", "Cancelled"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    type = models.CharField(max_length=50, choices=BetType.choices, default=BetType.PAGEVIEWS)
    bet_parameters = models.JSONField(
        default=dict
    )  # Stores parameters that define the bet conditions, e.g., URL pattern, event criteria
    closing_date = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    probability_distribution_interval = models.IntegerField(default=600)  # In seconds, default 10 minutes
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    final_value = models.JSONField(
        null=True, blank=True
    )  # The actual final value when bet is settled, can store complex values

    def __str__(self) -> str:
        return f"{self.title} ({self.type})"

    __repr__ = sane_repr("team", "type", "title", "status")

    @property
    def is_active(self) -> bool:
        return self.status == BetDefinition.Status.ACTIVE and self.closing_date > timezone.now()

    @property
    def latest_probability_distribution(self) -> Optional["ProbabilityDistribution"]:
        return self.probability_distributions.order_by("-created_at").first()

    def settle(self, final_value: float) -> None:
        """Settle the bet with the final value and update all related bets."""
        self.final_value = final_value
        self.status = BetDefinition.Status.SETTLED
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
    def buckets(self) -> list[dict[str, float]]:
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

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        CANCELLED = "cancelled", "Cancelled"

    bet_definition = models.ForeignKey(BetDefinition, on_delete=models.CASCADE, related_name="bets")
    probability_distribution = models.ForeignKey(ProbabilityDistribution, on_delete=models.CASCADE, related_name="bets")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bets")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # The monetary amount the user is wagering
    predicted_value = (
        models.JSONField()
    )  # The value/range/condition the user is betting on (can be a single value, range, or complex condition)
    potential_payout = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    def __str__(self) -> str:
        return f"Bet on {self.bet_definition.title} - {self.amount}"

    __repr__ = sane_repr("bet_definition", "user", "team", "amount", "status")

    def settle(self, final_value: float) -> None:
        """
        Settle the bet based on the final value.
        """
        # Check if the bet is already settled
        if self.status != Bet.Status.ACTIVE:
            return

        # Determine if the bet was won based on the prediction type
        prediction_matched = False

        # Handle different prediction types
        if isinstance(self.predicted_value, int | float) or (
            isinstance(self.predicted_value, dict) and "value" in self.predicted_value
        ):
            # Simple value prediction
            predicted = (
                self.predicted_value if isinstance(self.predicted_value, int | float) else self.predicted_value["value"]
            )
            if isinstance(final_value, int | float):
                prediction_matched = predicted == final_value
            elif isinstance(final_value, dict) and "value" in final_value:
                prediction_matched = predicted == final_value["value"]

        elif isinstance(self.predicted_value, dict) and "range" in self.predicted_value:
            # Range prediction
            min_val = self.predicted_value["range"][0]
            max_val = self.predicted_value["range"][1]

            if isinstance(final_value, int | float):
                prediction_matched = min_val <= final_value <= max_val
            elif isinstance(final_value, dict) and "value" in final_value:
                prediction_matched = min_val <= final_value["value"] <= max_val

        elif isinstance(self.predicted_value, dict) and "condition" in self.predicted_value:
            # Complex condition (e.g., greater than, less than)
            condition = self.predicted_value["condition"]
            threshold = self.predicted_value["threshold"]

            if isinstance(final_value, int | float):
                actual_value = final_value
            elif isinstance(final_value, dict) and "value" in final_value:
                actual_value = final_value["value"]
            else:
                actual_value = None

            if actual_value is not None:
                if condition == "gt":
                    prediction_matched = actual_value > threshold
                elif condition == "lt":
                    prediction_matched = actual_value < threshold
                elif condition == "gte":
                    prediction_matched = actual_value >= threshold
                elif condition == "lte":
                    prediction_matched = actual_value <= threshold

        if prediction_matched:
            self.status = Bet.Status.WON

            # Credit the user's wallet with the payout
            TransactionLedger.objects.create_transaction(
                user=self.user,
                team_id=str(self.team.id),
                transaction_type="bet_win",  # Use string value instead of enum
                amount=self.potential_payout,
                reference_id=str(self.id),
                description=f"Won bet on {self.bet_definition.title}",
            )
        else:
            self.status = Bet.Status.LOST

        self.save(update_fields=["status"])


class TransactionLedgerManager(models.Manager):
    def create_transaction(
        self,
        user: User,
        team_id: str,
        transaction_type: str,
        amount: float,
        reference_id: str | None = None,
        description: str = "",
    ) -> tuple["TransactionLedger", "TransactionLedger"]:
        """
        Create a double-entry bookkeeping transaction.
        Returns a tuple of (debit_entry, credit_entry)
        """
        reference_id = reference_id or str(uuid.uuid4())

        # Create debit entry (user's wallet)
        debit_entry = self.create(
            user=user,
            team_id=team_id,
            entry_type="debit",
            transaction_type=transaction_type,
            amount=amount,
            reference_id=reference_id,
            description=description,
        )

        # Create credit entry (system account)
        credit_entry = self.create(
            user=user,
            team_id=team_id,
            entry_type="credit",
            transaction_type=transaction_type,
            amount=amount,
            reference_id=reference_id,
            description=description,
        )

        return debit_entry, credit_entry

    def get_wallet_balance(self, user: User, team_id: Optional[str] = None) -> float:
        """
        Calculate the wallet balance for a user, optionally filtered by team_id.
        """
        query = self.filter(user=user)
        if team_id:
            query = query.filter(team_id=team_id)

        # For wallet balance, we need to consider transaction types:
        # - Deposits (onboarding, bet_win) increase balance
        # - Withdrawals (bet_place) decrease balance

        # Calculate deposits (money coming in)
        deposits = (
            query.filter(transaction_type__in=["onboarding", "bet_win"], entry_type="debit").aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

        # Calculate withdrawals (money going out)
        withdrawals = (
            query.filter(transaction_type="bet_place", entry_type="debit").aggregate(total=Sum("amount"))["total"] or 0
        )

        # Balance is deposits minus withdrawals
        balance = deposits - withdrawals
        return balance


class TransactionLedger(UUIDModel, CreatedMetaFields):
    """
    Double-entry bookkeeping ledger for tracking all financial transactions.
    """

    class EntryType(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    class TransactionType(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        BET_PLACE = "bet_place", "Bet Placement"
        BET_WIN = "bet_win", "Bet Win"
        ONBOARDING = "onboarding", "Onboarding Bonus"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    team_id = models.CharField(max_length=100)  # Store team ID as string to avoid cascade deletion
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference_id = models.CharField(
        max_length=100, blank=True, null=True
    )  # Optional field used to link related transactions
    description = models.TextField(blank=True)

    objects = TransactionLedgerManager()

    def __str__(self) -> str:
        return f"{self.entry_type.capitalize()} - {self.amount} - {self.transaction_type}"

    __repr__ = sane_repr("user", "team_id", "entry_type", "transaction_type", "amount")


class UserWallet(UUIDModel, CreatedMetaFields):
    """
    Database model for user wallets. Each user has one wallet.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="wallet")
    is_active = models.BooleanField(default=True)
    last_transaction_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Wallet for {self.user.email}"

    __repr__ = sane_repr("user", "is_active")


class Wallet:
    """
    Utility class for wallet operations.
    """

    @staticmethod
    def get_balance(user: User, team_id: Optional[str] = None) -> float:
        """Get the current wallet balance for a user, optionally filtered by team_id."""
        return TransactionLedger.objects.get_wallet_balance(user, team_id)

    @staticmethod
    def get_or_create_wallet(user: User) -> UserWallet:
        """Get or create a wallet for a user."""
        wallet, created = UserWallet.objects.get_or_create(user=user)
        return wallet

    @staticmethod
    def add_onboarding_bonus(
        user: User, team_id: str, amount: float = 1000.0
    ) -> tuple[TransactionLedger, TransactionLedger]:
        """Add the initial onboarding bonus to a user's wallet."""
        # Ensure user has a wallet
        Wallet.get_or_create_wallet(user)

        result = TransactionLedger.objects.create_transaction(
            user=user,
            team_id=team_id,
            transaction_type="onboarding",
            amount=amount,
            description="Initial onboarding bonus",
        )

        return result

    @staticmethod
    def place_bet(user: User, bet: Bet) -> tuple[TransactionLedger, TransactionLedger]:
        """Deduct the bet amount from the wallet."""
        # Ensure user has a wallet
        Wallet.get_or_create_wallet(user)

        return TransactionLedger.objects.create_transaction(
            user=user,
            team_id=str(bet.team.id),
            transaction_type="bet_place",  # Use string value instead of enum
            amount=bet.amount,
            reference_id=str(bet.id),
            description=f"Bet on {bet.bet_definition.title}",
        )

    @staticmethod
    def has_sufficient_funds(user: User, team_id: str, amount: float) -> bool:
        """Check if the user has sufficient funds in their wallet for a given amount."""
        balance = Wallet.get_balance(user, team_id)
        return balance >= amount
