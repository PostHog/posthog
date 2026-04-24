import pytest
from posthog.test.base import BaseTest

from posthog.models import LimitIncreaseRequest, LimitIncreaseRequestStatus, TeamLimitOverride
from posthog.resource_limits import LimitExceeded, check_count_limit, get_limit
from posthog.resource_limits.registry import REGISTRY, LimitDefinition


class TestGetLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.key = "analytics.max_dashboards_per_team"

    def test_returns_default_when_no_override(self) -> None:
        assert get_limit(team=self.team, key=self.key) == 500

    def test_returns_team_override(self) -> None:
        TeamLimitOverride.objects.create(
            team=self.team,
            limit_key=self.key,
            value=1000,
            reason="test",
        )
        assert get_limit(team=self.team, key=self.key) == 1000

    def test_null_value_override_is_unlimited(self) -> None:
        TeamLimitOverride.objects.create(
            team=self.team,
            limit_key=self.key,
            value=None,
            reason="unlimited grant",
        )
        assert get_limit(team=self.team, key=self.key) is None


class TestCheckCountLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.key = "analytics.max_dashboards_per_team"

    def test_below_limit_is_noop(self) -> None:
        check_count_limit(team=self.team, key=self.key, current_count=10, user=self.user)
        assert LimitIncreaseRequest.objects.count() == 0

    def test_at_limit_raises_and_creates_request(self) -> None:
        with pytest.raises(LimitExceeded) as exc_info:
            check_count_limit(team=self.team, key=self.key, current_count=500, user=self.user)
        assert exc_info.value.limit_key == self.key
        assert exc_info.value.limit == 500
        assert exc_info.value.current == 500
        assert exc_info.value.request_id is not None
        assert exc_info.value.extra["request"]["id"] == exc_info.value.request_id

        request = LimitIncreaseRequest.objects.get(id=exc_info.value.request_id)
        assert request.team_id == self.team.id
        assert request.limit_key == self.key
        assert request.limit_at_first_hit == 500
        assert request.count_at_first_hit == 500
        assert request.status == LimitIncreaseRequestStatus.PENDING
        assert request.requested_by_id == self.user.id
        assert request.hit_count == 1
        assert request.justification == ""

    def test_repeat_hits_bump_the_same_row(self) -> None:
        for _ in range(3):
            with pytest.raises(LimitExceeded):
                check_count_limit(team=self.team, key=self.key, current_count=500, user=self.user)
        assert LimitIncreaseRequest.objects.count() == 1
        request = LimitIncreaseRequest.objects.get()
        assert request.hit_count == 3

    def test_customer_justification_is_preserved_on_re_hit(self) -> None:
        with pytest.raises(LimitExceeded) as exc_info:
            check_count_limit(team=self.team, key=self.key, current_count=500, user=self.user)
        assert exc_info.value.request_id is not None
        request = LimitIncreaseRequest.objects.get(id=exc_info.value.request_id)
        request.justification = "We run a hosting platform and each tenant gets its own dashboard."
        request.save(update_fields=["justification"])

        with pytest.raises(LimitExceeded):
            check_count_limit(team=self.team, key=self.key, current_count=500, user=self.user)

        request.refresh_from_db()
        assert request.justification == "We run a hosting platform and each tenant gets its own dashboard."
        assert request.hit_count == 2

    def test_override_raises_the_effective_limit(self) -> None:
        TeamLimitOverride.objects.create(
            team=self.team,
            limit_key=self.key,
            value=1000,
            reason="bump",
        )
        check_count_limit(team=self.team, key=self.key, current_count=500, user=self.user)
        with pytest.raises(LimitExceeded) as exc_info:
            check_count_limit(team=self.team, key=self.key, current_count=1000, user=self.user)
        assert exc_info.value.limit == 1000


class TestRegistryShape:
    def test_every_entry_key_matches_its_dict_key(self) -> None:
        for dict_key, defn in REGISTRY.items():
            assert defn.key == dict_key, f"Registry key {dict_key} does not match LimitDefinition.key={defn.key}"

    def test_every_entry_has_non_empty_description(self) -> None:
        for defn in REGISTRY.values():
            assert defn.description.strip(), f"Limit {defn.key} has an empty description"

    def test_entries_are_limit_definition_instances(self) -> None:
        for defn in REGISTRY.values():
            assert isinstance(defn, LimitDefinition)
