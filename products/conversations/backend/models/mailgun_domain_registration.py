from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class MailgunDomainRegistration(UUIDModel):
    """A sending domain that this region registered in the Mailgun account.

    Several regions share one Mailgun account, so a domain with no support channel here may
    still belong to a channel in another region. The cleanup task only deletes domains listed
    here, and only while Mailgun still reports the same domain id. No team foreign key: the row
    must outlive the team so the cleanup can still find the domain.
    """

    domain = models.CharField(max_length=255, unique=True)
    mailgun_domain_id = models.CharField(max_length=64, blank=True, default="")
    registered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_mailgun_domain_registration"
