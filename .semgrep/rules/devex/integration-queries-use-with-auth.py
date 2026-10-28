# Test cases for integration-queries-use-with-auth.
# ruff: noqa

from posthog.models.integration import ANY, Integration
from posthog.models.integration import Integration as TeamIntegration
from posthog.models.integration import model

team_id = 1

# ruleid: integration-queries-use-with-auth
Integration.objects.filter(team_id=team_id, kind="github").first()

# ruleid: integration-queries-use-with-auth
Integration.objects.create(team_id=team_id, kind="github")

# ruleid: integration-queries-use-with-auth
Integration.objects.all()

# ruleid: integration-queries-use-with-auth
Integration.objects.filter(team_id=team_id).with_auth(ANY)

# ruleid: integration-queries-use-with-auth
manager = Integration.objects

# ruleid: integration-queries-use-with-auth
model.Integration.objects.get(id=1)

# ruleid: integration-queries-use-with-auth
TeamIntegration.objects.filter(team_id=team_id)

# ok: integration-queries-use-with-auth
Integration.objects.with_auth(Integration.AuthType.APP).filter(team_id=team_id, kind="github").first()

# ok: integration-queries-use-with-auth
Integration.objects.with_auth(ANY).get_or_create(team_id=team_id, kind="github")

# ok: integration-queries-use-with-auth
model.Integration.objects.with_auth(ANY).filter(team_id=team_id)

# ok: integration-queries-use-with-auth
TeamIntegration.objects.with_auth(ANY).filter(team_id=team_id)

# ok: integration-queries-use-with-auth
Integration._base_manager.filter(team_id=team_id)
