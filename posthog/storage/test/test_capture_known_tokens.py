from posthog.test.base import BaseTest

from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL
from posthog.storage.capture_known_tokens import SWEEP_MARKER_KEY, forget_token, sweep_known_tokens, token_key


class TestCaptureKnownTokens(BaseTest):
    def setUp(self):
        super().setUp()
        self.redis = get_client(PLUGINS_RELOAD_REDIS_URL)
        self.redis.flushall()

    def test_saving_a_team_marks_its_token_known_before_any_sweep_runs(self):
        # Capture refuses an unknown token, so a project must be usable the moment
        # it exists rather than after the next sweep.
        team = Team.objects.create(organization=self.organization, name="fresh project")

        assert self.redis.get(token_key(team.api_token)) == b"1"

    def test_sweep_covers_teams_and_publishes_the_freshness_marker(self):
        team = Team.objects.create(organization=self.organization, name="swept project")
        self.redis.flushall()

        written = sweep_known_tokens()

        assert written >= 1
        assert self.redis.get(token_key(team.api_token)) == b"1"
        assert self.redis.get(SWEEP_MARKER_KEY) is not None

    def test_a_token_that_was_never_written_is_absent(self):
        sweep_known_tokens()

        assert self.redis.get(token_key("phc_not_a_real_project_token")) is None

    def test_deleting_a_team_forgets_its_token(self):
        team = Team.objects.create(organization=self.organization, name="doomed project")
        token = team.api_token
        assert self.redis.get(token_key(token)) == b"1"

        team.delete()

        assert self.redis.get(token_key(token)) is None

    def test_entries_carry_an_expiry_so_a_stopped_sweep_thins_the_projection_out(self):
        team = Team.objects.create(organization=self.organization, name="expiring project")

        assert self.redis.ttl(token_key(team.api_token)) > 0

    def test_forgetting_an_empty_token_is_a_no_op(self):
        forget_token("")
