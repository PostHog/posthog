from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.management.commands.migrate_ses_tenants import migrate_ses_tenants
from posthog.models.integration import Integration


class _FakeSESv2Client:
    def __init__(self):
        self.created_tenants: list[str] = []
        self.associations: list[tuple[str, str]] = []

    def get_caller_identity(self):
        return {"Account": "123456789012"}

    def create_tenant(self, TenantName: str, Tags: list[dict]):  # noqa: N803
        # emulate idempotency externally in test assertions
        if TenantName in self.created_tenants:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "AlreadyExistsException", "Message": "Tenant exists"}}, "CreateTenant")
        self.created_tenants.append(TenantName)
        return {"TenantName": TenantName}

    def create_tenant_resource_association(self, TenantName: str, ResourceArn: str):  # noqa: N803
        # emulate idempotency externally in test assertions
        pair = (TenantName, ResourceArn)
        if pair in self.associations:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "AlreadyExistsException", "Message": "Association exists"}},
                "CreateTenantResourceAssociation",
            )
        self.associations.append(pair)
        return {"TenantName": TenantName, "ResourceArn": ResourceArn}


class TestMigrateSESTenants(BaseTest):
    def setUp(self):
        super().setUp()
        # Two SES email integrations on the same domain (should dedupe by (team, domain))
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="noreply@example.com",
            config={"domain": "example.com", "provider": "ses"},
            created_by=self.user,
        )
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="alerts@example.com",
            config={"domain": "example.com", "provider": "ses"},
            created_by=self.user,
        )
        # Non-SES provider should be ignored
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="ops@other.com",
            config={"domain": "other.com", "provider": "mailjet"},
            created_by=self.user,
        )

    @override_settings(SES_ACCESS_KEY_ID="test", SES_SECRET_ACCESS_KEY="test", SES_REGION="us-east-1", SES_ENDPOINT="")
    @patch("posthog.management.commands.migrate_ses_tenants.boto3.client")
    def test_dry_run(self, mock_boto_client):
        # Arrange stub clients
        sesv2 = _FakeSESv2Client()
        mock_boto_client.side_effect = lambda service, **kwargs: sesv2

        # Act: dry-run should not attempt create calls but will still resolve account id
        migrate_ses_tenants(team_ids=[], domains=[], dry_run=True)

        # Assert: no tenants/associations performed
        assert sesv2.created_tenants == []
        assert sesv2.associations == []

    @override_settings(SES_ACCESS_KEY_ID="test", SES_SECRET_ACCESS_KEY="test", SES_REGION="us-east-1", SES_ENDPOINT="")
    @patch("posthog.management.commands.migrate_ses_tenants.boto3.client")
    def test_migrate_for_team(self, mock_boto_client):
        sesv2 = _FakeSESv2Client()
        mock_boto_client.side_effect = lambda service, **kwargs: sesv2

        migrate_ses_tenants(team_ids=[self.team.id], domains=[], dry_run=False)

        # Deduped: only one tenant and one association for (team, example.com)
        assert sesv2.created_tenants == [f"team-{self.team.id}"]
        expected_arn = f"arn:aws:ses:us-east-1:123456789012:identity/example.com"
        assert sesv2.associations == [(f"team-{self.team.id}", expected_arn)]

    @override_settings(SES_ACCESS_KEY_ID="test", SES_SECRET_ACCESS_KEY="test", SES_REGION="eu-west-1", SES_ENDPOINT="")
    @patch("posthog.management.commands.migrate_ses_tenants.boto3.client")
    def test_migrate_for_domain_filter(self, mock_boto_client):
        sesv2 = _FakeSESv2Client()
        mock_boto_client.side_effect = lambda service, **kwargs: sesv2

        # Use domains filter; should match example.com only
        migrate_ses_tenants(team_ids=[], domains=["example.com"], dry_run=False)

        assert sesv2.created_tenants == [f"team-{self.team.id}"]
        expected_arn = f"arn:aws:ses:eu-west-1:123456789012:identity/example.com"
        assert sesv2.associations == [(f"team-{self.team.id}", expected_arn)]

    @override_settings(SES_ACCESS_KEY_ID="test", SES_SECRET_ACCESS_KEY="test", SES_REGION="us-east-1", SES_ENDPOINT="")
    @patch("posthog.management.commands.migrate_ses_tenants.boto3.client")
    def test_idempotent_on_repeated_run(self, mock_boto_client):
        sesv2 = _FakeSESv2Client()
        mock_boto_client.side_effect = lambda service, **kwargs: sesv2

        # First run creates
        migrate_ses_tenants(team_ids=[self.team.id], domains=[], dry_run=False)
        # Second run should hit AlreadyExistsException internally and not error
        migrate_ses_tenants(team_ids=[self.team.id], domains=[], dry_run=False)

        # Still only one tenant and association recorded
        assert sesv2.created_tenants == [f"team-{self.team.id}"]
        expected_arn = f"arn:aws:ses:us-east-1:123456789012:identity/example.com"
        assert sesv2.associations == [(f"team-{self.team.id}", expected_arn)]
