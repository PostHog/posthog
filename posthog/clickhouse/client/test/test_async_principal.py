from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.auth import ProjectSecretAPIKeyUser, TeamSecretTokenUser
from posthog.clickhouse.client.async_principal import rebuild_principal, serialize_principal
from posthog.models import Organization, Team
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from posthog.shared_link_user import SharedLinkUser
from posthog.synthetic_user import SyntheticUser


class TestAsyncPrincipal(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.other_team = Team.objects.create(organization=self.organization)

    def test_real_user_has_no_principal_reference(self):
        user = User.objects.create_user("principal@posthog.com", "pw", "Test")
        self.assertIsNone(serialize_principal(user))

    def test_none_has_no_principal_reference(self):
        self.assertIsNone(serialize_principal(None))

    def test_shared_link_principal_round_trips(self):
        sharing_configuration = SharingConfiguration.objects.create(team=self.team, enabled=True)

        rebuilt = rebuild_principal(serialize_principal(SharedLinkUser(sharing_configuration)), self.team)

        assert isinstance(rebuilt, SharedLinkUser)
        self.assertEqual(rebuilt.sharing_configuration.pk, sharing_configuration.pk)

    def test_project_secret_api_key_principal_round_trips(self):
        key = ProjectSecretAPIKey.objects.create(team=self.team, label="test")

        rebuilt = rebuild_principal(serialize_principal(ProjectSecretAPIKeyUser(key)), self.team)

        assert isinstance(rebuilt, ProjectSecretAPIKeyUser)
        self.assertEqual(rebuilt.project_secret_api_key.pk, key.pk)

    def test_team_secret_token_principal_round_trips(self):
        self.team.secret_api_token = "phs_test"
        self.team.save()

        rebuilt = rebuild_principal(serialize_principal(TeamSecretTokenUser(self.team)), self.team)

        assert isinstance(rebuilt, SyntheticUser)
        self.assertEqual(rebuilt.current_team_id, self.team.id)

    @parameterized.expand(
        [
            ("cleared", None),
            # Rotation is how a leaked token is revoked, so the queued query must stop working too.
            ("rotated", "phs_rotated"),
        ]
    )
    def test_team_secret_token_no_longer_matching_does_not_rebuild(self, _name, new_token):
        self.team.secret_api_token = "phs_test"
        self.team.save()
        ref = serialize_principal(TeamSecretTokenUser(self.team))
        Team.objects.filter(pk=self.team.pk).update(secret_api_token=new_token)
        self.team.refresh_from_db()

        self.assertIsNone(rebuild_principal(ref, self.team))

    @parameterized.expand(
        [
            # Every revocation channel the request path honors has to revoke a queued query too.
            ("disabled", {"enabled": False}),
            ("expired", {"expires_at": timezone.now() - timedelta(seconds=1)}),
            # A password-protected share is authorized by a JWT against an active SharePassword,
            # which the reference cannot represent, so rebuilding from the config alone would skip it.
            ("password_protected", {"password_required": True}),
        ]
    )
    def test_revoked_share_link_does_not_rebuild(self, _name, revocation):
        sharing_configuration = SharingConfiguration.objects.create(team=self.team, enabled=True)
        ref = serialize_principal(SharedLinkUser(sharing_configuration))
        SharingConfiguration.objects.filter(pk=sharing_configuration.pk).update(**revocation)

        self.assertIsNone(rebuild_principal(ref, self.team))

    @patch("posthog.auth._organization_disallows_public_sharing", return_value=True)
    def test_share_link_does_not_rebuild_when_the_org_disallows_public_sharing(self, _mock):
        sharing_configuration = SharingConfiguration.objects.create(team=self.team, enabled=True)
        ref = serialize_principal(SharedLinkUser(sharing_configuration))

        self.assertIsNone(rebuild_principal(ref, self.team))

    def test_deleted_project_secret_api_key_does_not_rebuild(self):
        key = ProjectSecretAPIKey.objects.create(team=self.team, label="test")
        ref = serialize_principal(ProjectSecretAPIKeyUser(key))
        key.delete()

        self.assertIsNone(rebuild_principal(ref, self.team))

    @parameterized.expand(
        [
            ("shared_link", lambda team: {"kind": "shared_link", "id": _shared_link_pk(team)}),
            ("psak", lambda team: {"kind": "psak", "id": _psak_pk(team)}),
        ]
    )
    def test_principal_from_another_team_does_not_rebuild(self, _name, build_ref):
        self.assertIsNone(rebuild_principal(build_ref(self.other_team), self.team))

    @parameterized.expand(
        [
            ("empty", {}),
            ("unknown_kind", {"kind": "root"}),
            ("not_a_dict", "shared_link"),
            ("shared_link_with_missing_id", {"kind": "shared_link", "id": 123456789}),
            # A malformed id must resolve to None, not raise: Postgres rejects a non-integer pk
            # lookup, and the task would then burn every retry on the same payload.
            ("shared_link_with_malformed_id", {"kind": "shared_link", "id": "abc"}),
            # The PSAK pk is a CharField, so an integer is malformed there rather than coercible.
            ("psak_with_malformed_id", {"kind": "psak", "id": 123456789}),
        ]
    )
    def test_unresolvable_reference_does_not_rebuild(self, _name, ref):
        self.assertIsNone(rebuild_principal(ref, self.team))


def _shared_link_pk(team: Team) -> int:
    return SharingConfiguration.objects.create(team=team, enabled=True).pk


def _psak_pk(team: Team) -> str:
    return ProjectSecretAPIKey.objects.create(team=team, label="test").pk
