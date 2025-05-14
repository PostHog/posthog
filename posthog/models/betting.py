from django.db import models
from django.utils import timezone
from django.db.models import Sum, Q
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
    bet_parameters = models.JSONField(default=dict)  # JSON structure for bet parameters, examples:
    # For pageviews: {
    #   "url": "/path/to/page",           # URL pattern to match
    #   "filters": {                      # Additional filters (optional)
    #     "country": ["US", "CA"],        # Filter by country
    #     "browser": ["Chrome", "Safari"] # Filter by browser
    #   }
    # }
    # Can be extended for other bet types with different parameters
    bucket_definitions = models.JSONField(default=list)  # Array of bucket definitions:
    # For pageviews: [
    #   {"min": 100, "max": 200},  # Bucket for 100-200 pageviews
    #   {"min": 201, "max": 300},  # Bucket for 201-300 pageviews
    #   {"min": 301, "max": 400}   # Bucket for 301-400 pageviews
    # ]
    # Used to ensure consistent buckets across probability distribution refreshes
    closing_date = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    probability_distribution_interval = models.IntegerField(default=600)  # In seconds, default 10 minutes
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    final_value = models.JSONField(null=True, blank=True)  # The actual final value when bet is settled. Can be:
    # 1. Simple value: 123 (number)
    # 2. Complex object: {
    #    "value": 123,                    # The primary value
    #    "confidence": 0.95,              # Confidence level (optional)
    #    "metadata": {                    # Additional metadata (optional)
    #      "source": "analytics",         # Source of the data
    #      "calculation_method": "sum"    # How the value was calculated
    #    }
    # }

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
    distribution_data = models.JSONField()  # Array of probability distribution buckets:
    # [
    #   {"value": 100, "probability": 0.2},  # 20% chance of value being 100
    #   {"value": 200, "probability": 0.5},  # 50% chance of value being 200
    #   {"value": 300, "probability": 0.3}   # 30% chance of value being 300
    # ]
    # Probabilities should sum to 1.0
    # Can be extended to support ranges:
    # [
    #   {"range": [0, 100], "probability": 0.3},    # 30% chance of value between 0-100
    #   {"range": [101, 200], "probability": 0.4},  # 40% chance of value between 101-200
    #   {"range": [201, 300], "probability": 0.3}   # 30% chance of value between 201-300
    # ]``

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
    predicted_value = models.JSONField()  # The prediction the user is betting on. Can be one of:
    # 1. Simple value: 123 (number)
    # 2. Value object: {"value": 123}
    # 3. Range: {"range": [100, 200]}  # Predicting value will be between 100-200
    # 4. Condition: {                  # Predicting value will meet a condition
    #    "condition": "gt",            # Condition type: "gt" (>), "lt" (<), "gte" (>=), "lte" (<=)
    #    "threshold": 150              # Threshold value for the condition
    # }
    # 5. Complex prediction: {         # For future extension
    #    "type": "compound",           # Type of prediction
    #    "operator": "and",            # Logical operator: "and", "or"
    #    "conditions": [...]           # Array of conditions
    # }
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
        source: str | None = None,
        destination: str | None = None,
    ) -> tuple["TransactionLedger", "TransactionLedger"]:
        """
        Create a double-entry bookkeeping transaction.
        Returns a tuple of (debit_entry, credit_entry)
        """
        reference_id = reference_id or str(uuid.uuid4())

        # Set default source and destination based on transaction type
        if source is None or destination is None:
            if transaction_type == "onboarding":
                # For onboarding bonus: Money comes from equity, goes to user's wallet
                source = "equity" if source is None else source
                destination = "wallet" if destination is None else destination
            elif transaction_type == "bet_place":
                # For bet placement: Money comes from user's wallet, goes to pool
                source = "wallet" if source is None else source
                destination = "pool" if destination is None else destination
            elif transaction_type == "bet_win":
                # For bet win: Money comes from pool, goes to user's wallet
                source = "pool" if source is None else source
                destination = "wallet" if destination is None else destination
            elif transaction_type == "deposit":
                # For deposit: Money comes from stripe, goes to user's wallet
                source = "stripe" if source is None else source
                destination = "wallet" if destination is None else destination
            else:
                # Default fallback
                source = "wallet" if source is None else source
                destination = "bank" if destination is None else destination

        # Determine the user for each entry based on source and destination
        debit_user = None
        credit_user = None

        # For user wallet transactions, associate the entry with the user
        if source == "wallet":
            debit_user = user
        if destination == "wallet":
            credit_user = user

        # For onboarding transactions, associate the credit entry with the user
        if transaction_type == "onboarding" and credit_user is None:
            credit_user = user  # Associate the receiving end with the user

        # Create debit entry (money leaving the source)
        debit_entry = self.create(
            user=debit_user,  # Will be None for system accounts
            team_id=team_id,
            entry_type="debit",
            transaction_type=transaction_type,
            amount=amount,
            source=source,
            destination=destination,
            reference_id=reference_id,
            description=description,
        )

        # Create credit entry (money entering the destination)
        credit_entry = self.create(
            user=credit_user,  # Will be None for system accounts
            team_id=team_id,
            entry_type="credit",
            transaction_type=transaction_type,
            amount=amount,
            source=source,
            destination=destination,
            reference_id=reference_id,
            description=description,
        )

        return debit_entry, credit_entry

    def get_wallet_balance(self, user: User, team_id: Optional[str] = None) -> float:
        """
        Calculate the wallet balance for a user, optionally filtered by team_id.

        In double-entry bookkeeping:
        - Credits increase the wallet balance (money coming in)
        - Debits decrease the wallet balance (money going out)

        We also need to consider the destination/source to ensure we're only counting
        transactions that affect the user's wallet.
        """
        query = self.filter(user=user)
        if team_id:
            query = query.filter(team_id=team_id)

        # Only consider transactions involving the user's wallet
        wallet_query = query.filter(Q(source="wallet") | Q(destination="wallet"))

        # Credits to wallet (money coming in)
        credits = (
            wallet_query.filter(destination="wallet", entry_type="credit").aggregate(total=Sum("amount"))["total"] or 0
        )

        # Debits from wallet (money going out)
        debits = wallet_query.filter(source="wallet", entry_type="debit").aggregate(total=Sum("amount"))["total"] or 0

        # Balance is credits minus debits
        balance = credits - debits

        return balance


class TransactionLedger(UUIDModel, CreatedMetaFields):
    """
    Double-entry bookkeeping ledger for tracking all financial transactions.
    Each transaction records the movement of funds between a source and destination.
    """

    class EntryType(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    class TransactionType(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        BET_PLACE = "bet_place", "Bet Placement"
        BET_WIN = "bet_win", "Bet Win"
        ONBOARDING = "onboarding", "Onboarding Bonus"

    class SourceType(models.TextChoices):
        WALLET = "wallet", "User Wallet"
        BANK = "bank", "Hoggy Bank"
        STRIPE = "stripe", "Stripe"
        POOL = "pool", "Pool"
        EQUITY = "equity", "Capital Account"  # For money creation

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions", null=True, blank=True)
    team_id = models.CharField(max_length=100)  # Store team ID as string to avoid cascade deletion
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    source = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.WALLET)
    destination = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.BANK)
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
