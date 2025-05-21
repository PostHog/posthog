from django.db import models, transaction
from django.db.models import Sum, Q
from posthog.models.user import User
from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
import uuid
from typing import Optional
from datetime import datetime

class TransactionType(models.TextChoices):
    """Types of transactions in the wallet system."""
    INITIALIZATION = "initialization", "Initialization"  # Initial wallet setup
    REWARD = "reward", "Reward"  # Platform rewards for actions
    REDEMPTION = "redemption", "Redemption"  # Spending rewards on merge credits
    REFUND = "refund", "Refund"  # For failed redemptions/transactions
    EXPIRY = "expiry", "Expiry"  # When rewards expire
    ADJUSTMENT = "adjustment", "Adjustment"  # Manual corrections by admins

class SourceType(models.TextChoices):
    """Sources and destinations for wallet transactions."""
    WALLET = "wallet", "User Wallet"  # User's personal wallet
    BANK = "bank", "Hoggy Bank"  # System account for all non-user transactions (redemptions, expiries, refunds)
    EQUITY = "equity", "Capital Account"  # System account for money creation (e.g. initial wallet setup)
    REWARDS = "rewards", "Rewards Pool"  # Platform rewards pool

class EntryType(models.TextChoices):
    """Types of ledger entries in double-entry bookkeeping."""
    DEBIT = "debit", "Debit"  # Money leaving an account
    CREDIT = "credit", "Credit"  # Money entering an account

class InsufficientFundsError(Exception):
    pass

class TransactionLedgerManager(models.Manager):
    @transaction.atomic
    def create_transaction(
        self,
        user: User,
        transaction_type: str,
        amount: float,
        reference_id: str | None = None,
        description: str = "",
        metadata: dict | None = {},
    ) -> tuple["TransactionLedger", "TransactionLedger"]:
        """
        Create a double-entry bookkeeping transaction.
        Returns a tuple of (debit_entry, credit_entry)
        """
        # Validate amount
        if amount <= 0:
            raise ValueError("Amount must be positive")

        # For deductions, validate balance
        if transaction_type in [TransactionType.REDEMPTION]:
            if not Wallet.has_sufficient_funds(user, amount):
                raise InsufficientFundsError(f"Insufficient funds for {amount}")

        reference_id = reference_id or str(uuid.uuid4())

        # Set default source and destination based on transaction type
        if transaction_type == TransactionType.INITIALIZATION:
            source = SourceType.EQUITY
            destination = SourceType.WALLET
        elif transaction_type == TransactionType.REWARD:
            source = SourceType.REWARDS
            destination = SourceType.WALLET
        elif transaction_type == TransactionType.REDEMPTION:
            source = SourceType.WALLET
            destination = SourceType.BANK
        elif transaction_type == TransactionType.REFUND:
            source = SourceType.BANK
            destination = SourceType.WALLET
        elif transaction_type == TransactionType.EXPIRY:
            source = SourceType.WALLET
            destination = SourceType.BANK
        else:
            source = SourceType.WALLET
            destination = SourceType.BANK

        # Determine the user for each entry based on source and destination
        debit_user = None
        credit_user = None

        # For user wallet transactions, associate the entry with the user
        if source == SourceType.WALLET:
            debit_user = user
        if destination == SourceType.WALLET:
            credit_user = user

        # For onboarding transactions, associate the credit entry with the user
        if transaction_type == TransactionType.INITIALIZATION and credit_user is None:
            credit_user = user

        # Create debit entry (money leaving the source)
        debit_entry = self.create(
            user=debit_user,
            entry_type=EntryType.DEBIT,
            transaction_type=transaction_type,
            amount=amount,
            source=source,
            destination=destination,
            reference_id=reference_id,
            description=description,
            metadata=metadata,
        )

        # Create credit entry (money entering the destination)
        credit_entry = self.create(
            user=credit_user,
            entry_type=EntryType.CREDIT,
            transaction_type=transaction_type,
            amount=amount,
            source=source,
            destination=destination,
            reference_id=reference_id,
            description=description,
            metadata=metadata,
        )

        return debit_entry, credit_entry

    def get_wallet_balance(self, user: User) -> float:
        """
        Calculate the wallet balance for a user.
        In double-entry bookkeeping:
        - Credits increase the wallet balance (money coming in)
        - Debits decrease the wallet balance (money going out)
        We also need to consider the destination/source to ensure we're only counting
        transactions that affect the user's wallet.
        """
        query = self.filter(user=user)

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

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions", null=True, blank=True)
    description = models.TextField(blank=True)
    
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    source = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.WALLET)
    destination = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.BANK)
    
    metadata = models.JSONField(default=dict, blank=True)
    reference_id = models.CharField(
        max_length=100, blank=True, null=True
    )  # Optional field used to link related transactions
    expires_at = models.DateTimeField(null=True, blank=True)  # For time-limited rewards

    objects = TransactionLedgerManager()

    def __str__(self) -> str:
        return f"{self.entry_type.capitalize()} - {self.amount} - {self.transaction_type}"

    __repr__ = sane_repr("user", "entry_type", "transaction_type", "amount")


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
    def get_balance(user: User) -> float:
        return TransactionLedger.objects.get_wallet_balance(user)
    
    @staticmethod
    def is_initialized(user: User) -> bool:
        return UserWallet.objects.filter(user=user).exists()

    @staticmethod
    def get_or_create_wallet(user: User) -> UserWallet:
        wallet, created = UserWallet.objects.get_or_create(user=user)
        return wallet

    @staticmethod
    def initialize_wallet(
        user: User, amount: float = 1000.0
    ) -> tuple[TransactionLedger, TransactionLedger]:
        Wallet.get_or_create_wallet(user)

        result = TransactionLedger.objects.create_transaction(
            user=user,
            transaction_type=TransactionType.INITIALIZATION,
            amount=amount,
            description="Initial wallet creation",
        )

        return result

    @staticmethod
    def has_sufficient_funds(user: User, amount: float) -> bool:
        """Check if the user has sufficient funds in their wallet for a given amount."""
        balance = Wallet.get_balance(user)
        return balance >= amount

    @staticmethod
    def add_funds(user: User, amount: float, description: str) -> tuple[TransactionLedger, TransactionLedger]:
        """Add funds to the user's wallet."""
        # Ensure user has a wallet
        Wallet.get_or_create_wallet(user)

        return TransactionLedger.objects.create_transaction(
            user=user,
            transaction_type=TransactionType.DEPOSIT,
            amount=amount,
            description=description,
        )
    
    @staticmethod
    def deduct_funds(user: User, amount: float, description: str) -> tuple[TransactionLedger, TransactionLedger]:
        """Deduct funds from the user's wallet."""
        return TransactionLedger.objects.create_transaction(
            user=user,
            transaction_type=TransactionType.WITHDRAWAL,
            amount=amount,
            description=description,
        )

    @staticmethod
    def add_reward(user: User, amount: float, description: str, expires_at: Optional[datetime] = None) -> tuple[TransactionLedger, TransactionLedger]:
        """Add reward funds to the user's wallet."""
        Wallet.get_or_create_wallet(user)
        
        return TransactionLedger.objects.create_transaction(
            user=user,
            transaction_type=TransactionType.REWARD,
            amount=amount,
            description=description,
            metadata={"expires_at": expires_at.isoformat() if expires_at else None},
        )

    @staticmethod
    def redeem_reward(user: User, amount: float, description: str) -> tuple[TransactionLedger, TransactionLedger]:
        """Redeem reward funds from the user's wallet."""
        return TransactionLedger.objects.create_transaction(
            user=user,
            transaction_type=TransactionType.REDEMPTION,
            amount=amount,
            description=description,
        )
