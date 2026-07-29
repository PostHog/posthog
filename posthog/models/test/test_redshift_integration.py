import pytest

from posthog.models.integration import Integration, RedshiftIntegration, RedshiftIntegrationError
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

pytestmark = pytest.mark.django_db


def _team_and_user() -> tuple[Team, User]:
    organization = Organization.objects.create(name="Test org")
    team = Team.objects.create(organization=organization, name="Test team")
    user = User.objects.create(email="test@posthog.com")
    return team, user


def test_redshift_password_integration_stores_password_in_sensitive_config() -> None:
    team, user = _team_and_user()

    integration = RedshiftIntegration.integration_from_config(
        team_id=team.id,
        name="prod-redshift",
        authentication_type="password",
        user="batch_exporter",
        password="secret",
        created_by=user,
    )

    assert integration.kind == Integration.IntegrationKind.REDSHIFT
    assert integration.integration_id == "prod-redshift"
    assert integration.config == {
        "name": "prod-redshift",
        "authentication_type": "password",
        "user": "batch_exporter",
    }
    assert integration.sensitive_config == {"password": "secret"}

    redshift = RedshiftIntegration(integration)
    assert redshift.authentication_type == "password"
    assert redshift.password == "secret"


def test_redshift_iam_role_integration_stores_role_config_without_database_password() -> None:
    team, user = _team_and_user()

    integration = RedshiftIntegration.integration_from_config(
        team_id=team.id,
        name="serverless-prod",
        authentication_type="iam_role",
        aws_role_arn="arn:aws:iam::123456789012:role/posthog-redshift",
        created_by=user,
    )

    assert integration.config == {
        "name": "serverless-prod",
        "authentication_type": "iam_role",
        "aws_role_arn": "arn:aws:iam::123456789012:role/posthog-redshift",
    }
    assert integration.sensitive_config == {}

    redshift = RedshiftIntegration(integration)
    assert redshift.authentication_type == "iam_role"
    assert redshift.aws_role_arn == "arn:aws:iam::123456789012:role/posthog-redshift"


def test_redshift_integration_rejects_missing_auth_specific_fields() -> None:
    team, user = _team_and_user()

    with pytest.raises(RedshiftIntegrationError, match="User and password must be provided"):
        RedshiftIntegration.integration_from_config(
            team_id=team.id,
            name="bad-password",
            authentication_type="password",
            user="batch_exporter",
            created_by=user,
        )

    with pytest.raises(RedshiftIntegrationError, match="IAM role ARN must be provided"):
        RedshiftIntegration.integration_from_config(
            team_id=team.id,
            name="bad-iam",
            authentication_type="iam_role",
            created_by=user,
        )


def test_redshift_integration_rejects_duplicate_name() -> None:
    team, user = _team_and_user()

    RedshiftIntegration.integration_from_config(
        team_id=team.id,
        name="prod-redshift",
        authentication_type="password",
        user="batch_exporter",
        password="secret",
        created_by=user,
    )

    with pytest.raises(RedshiftIntegrationError, match="An integration named 'prod-redshift' already exists"):
        RedshiftIntegration.integration_from_config(
            team_id=team.id,
            name="prod-redshift",
            authentication_type="iam_role",
            aws_role_arn="arn:aws:iam::123456789012:role/posthog-redshift",
            created_by=user,
        )
