from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.customer_analytics.backend.facade.enums import (
    AccountDocumentSource,
    AccountDocumentStatus,
    AccountDocumentType,
)


class AccountDocument(TeamScopedRootMixin, UUIDModel):
    """A business document attached to an account: a quote, an order form, a contract, or a link to one.

    The row holds metadata and a reference. A PandaDoc document is referenced by its PandaDoc id
    and rendered through the PandaDoc API, so an unsigned document stays live rather than being
    copied as a file. A plain link points at a document held elsewhere.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    account = models.ForeignKey("customer_analytics.Account", on_delete=models.CASCADE, related_name="documents")

    document_type = models.CharField(
        max_length=32, choices=AccountDocumentType.choices, default=AccountDocumentType.OTHER.value
    )
    title = models.CharField(max_length=512)
    status = models.CharField(
        max_length=16, choices=AccountDocumentStatus.choices, default=AccountDocumentStatus.DRAFT.value
    )
    source = models.CharField(
        max_length=16, choices=AccountDocumentSource.choices, default=AccountDocumentSource.LINK.value
    )

    external_url = models.URLField(max_length=2048, blank=True, default="")
    pandadoc_document_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # The raw PandaDoc status (for example `document.sent`) as last read from the PandaDoc API.
    # `status` is the normalized value the UI and SQL readers use.
    pandadoc_status = models.CharField(max_length=64, blank=True, default="")
    pandadoc_synced_at = models.DateTimeField(null=True, blank=True)

    effective_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "account", "-created_at"], name="idx_account_document_account"),
        ]
