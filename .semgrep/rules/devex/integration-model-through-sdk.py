# Test cases for integration-model-through-sdk.
# ruff: noqa

# ruleid: integration-model-through-sdk
from posthog.models import Integration

# ruleid: integration-model-through-sdk
from posthog.models import Integration, Team

# ruleid: integration-model-through-sdk
from posthog.models.integration import Integration as TeamIntegration

# ruleid: integration-model-through-sdk
from posthog.models.integration.model import Integration

# ruleid: integration-model-through-sdk
import posthog.models.integration.model

# ok: integration-model-through-sdk
from posthog.models.integration import SlackIntegration

# ok: integration-model-through-sdk
from posthog.integrations import IntegrationManager, IntegrationRecord

from django.apps import apps
from django.db import models
from django.db.models import F, Q
from django.db.models import ForeignKey

team_id = 1

# ruleid: integration-model-through-sdk
Integration.objects.filter(team_id=team_id, kind="github").first()

# ruleid: integration-model-through-sdk
TeamIntegration.objects.get(id=1)

# ruleid: integration-model-through-sdk
manager = posthog.models.integration.model.Integration.objects

# ruleid: integration-model-through-sdk
IntegrationRecord.objects.filter(team_id=team_id)

# ruleid: integration-model-through-sdk
facade_api.IntegrationRecord.objects.get(id=1)

# ruleid: integration-model-through-sdk
Integration._base_manager.filter(id=1)

# ruleid: integration-model-through-sdk
IntegrationRecord._default_manager.all()

# ruleid: integration-model-through-sdk
posthog.models.Integration._default_manager.all()

# ruleid: integration-model-through-sdk
TeamIntegration._base_manager.get(id=1)

# ok: integration-model-through-sdk
SlackThread._default_manager.all()

# ruleid: integration-model-through-sdk
model = apps.get_model("posthog", "Integration")

# ruleid: integration-model-through-sdk
model = apps.get_model("posthog.Integration")

# ruleid: integration-model-through-sdk
model = apps.get_model("posthog.integration")

# ok: integration-model-through-sdk
model = apps.get_model("posthog", "Team")

# ok: integration-model-through-sdk
model = apps.get_model("posthog", "UserIntegration")


class SlackThread(models.Model):
    # ruleid: integration-model-through-sdk
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE)
    # ruleid: integration-model-through-sdk
    other = models.ForeignKey("posthog.Integration", on_delete=models.SET_NULL, null=True)
    # ruleid: integration-model-through-sdk
    third = models.ForeignKey(to="posthog.Integration", on_delete=models.CASCADE)
    # ruleid: integration-model-through-sdk
    fourth = models.OneToOneField("posthog.Integration", on_delete=models.CASCADE)
    # ruleid: integration-model-through-sdk
    fifth = models.ForeignKey(IntegrationRecord, on_delete=models.CASCADE)
    # ruleid: integration-model-through-sdk
    sixth = models.ForeignKey("posthog.integration", on_delete=models.CASCADE)
    # ruleid: integration-model-through-sdk
    seventh = models.ManyToManyField("posthog.Integration", related_name="+")
    # ruleid: integration-model-through-sdk
    eighth = models.ManyToManyField(to=Integration, related_name="+")
    # ruleid: integration-model-through-sdk
    ninth = models.OneToOneField(to=IntegrationRecord, on_delete=models.CASCADE)
    # ruleid: integration-model-through-sdk
    tenth = ForeignKey("POSTHOG.INTEGRATION", on_delete=models.CASCADE)
    # ok: integration-model-through-sdk
    user_link = models.ForeignKey("posthog.UserIntegration", on_delete=models.CASCADE)
    # ok: integration-model-through-sdk
    org_links = models.ManyToManyField("posthog.OrganizationIntegration")
    # ok: integration-model-through-sdk
    integration_id_only = models.BigIntegerField(null=True)
    # ok: integration-model-through-sdk
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)


# ruleid: integration-model-through-sdk
SlackThread.objects.select_related("integration").all()

# ruleid: integration-model-through-sdk
SlackThread.objects.select_related("team", "slack_integration").all()

# ruleid: integration-model-through-sdk
SlackThread.objects.prefetch_related("integration__created_by").all()

# ok: integration-model-through-sdk
SlackThread.objects.select_related("team", "created_by").all()

# ok: integration-model-through-sdk
SlackThread.objects.select_related("github_user_integration").all()

# ruleid: integration-model-through-sdk
SlackThread.objects.filter(integration__kind="slack")

# ruleid: integration-model-through-sdk
SlackThread.objects.filter(team_id=team_id, slack_integration__config__team_id="T1")

# ruleid: integration-model-through-sdk
SlackThread.objects.exclude(Q(thread__integration__kind="slack"))

# ok: integration-model-through-sdk
SlackThread.objects.filter(integration_id=3)

# ok: integration-model-through-sdk
SlackThread.objects.filter(team_id=team_id)

# ok: integration-model-through-sdk
SlackThread.objects.filter(github_user_integration__isnull=True)

# ok: integration-model-through-sdk
SlackThread.objects.filter(organization_integration__kind="vercel")

# ruleid: integration-model-through-sdk
SlackThread.objects.values("id", "integration__kind")

# ruleid: integration-model-through-sdk
SlackThread.objects.values_list("slack_integration__config", flat=True)

# ruleid: integration-model-through-sdk
SlackThread.objects.order_by("-integration__created_at")

# ruleid: integration-model-through-sdk
SlackThread.objects.annotate(kind=F("thread__integration__kind"))

# ruleid: integration-model-through-sdk
SlackThread.objects.filter(**{"integration__kind": "slack"})

# ruleid: integration-model-through-sdk
SlackThread.objects.exclude(Q(**{"integration__config__team_id": "T1"}))

# ok: integration-model-through-sdk
SlackThread.objects.values("integration_id", "team__name")

# ok: integration-model-through-sdk
SlackThread.objects.order_by("-user_integration__created_at")

# ok: integration-model-through-sdk
SlackThread.objects.values_list("organization_integration__kind", flat=True)

# ok: integration-model-through-sdk
SlackThread.objects.filter(**{"integration_id": 3})


def handler(self, user, thread, integration, slack_integration, org_integration):
    # ruleid: integration-model-through-sdk
    user.integration_set.all()
    # ruleid: integration-model-through-sdk
    integration.save()
    # ruleid: integration-model-through-sdk
    thread.integration.save(update_fields=["config"])
    # ruleid: integration-model-through-sdk
    slack_integration.save()
    # ok: integration-model-through-sdk
    thread.save()
    # ok: integration-model-through-sdk
    org_integration.save()
    # ok: integration-model-through-sdk
    self.integration.save(update_fields=["config"])
    # ok: integration-model-through-sdk
    IntegrationManager.github.oauth.update(team_id, 1, config_patch={"a": 1})
