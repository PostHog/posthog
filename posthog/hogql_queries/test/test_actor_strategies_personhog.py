from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.schema import ActorsQuery

from posthog.hogql_queries.actor_strategies import PersonStrategy
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team
from posthog.test.persons import create_person, update_person


def _make_strategy(team) -> PersonStrategy:
    query = ActorsQuery(kind="ActorsQuery", select=["person"])
    paginator = HogQLHasMorePaginator(limit=100, offset=0)
    return PersonStrategy(team=team, query=query, paginator=paginator)


class TestPersonStrategyGetActors(BaseTest):
    def test_basic_person_lookup(self):
        person = create_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={"email": "test@example.com"},
        )

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(person.uuid)])

        assert len(result) == 1
        entry = result[str(person.uuid)]
        assert str(entry["id"]) == str(person.uuid)
        assert entry["properties"] == {"email": "test@example.com"}
        assert entry["is_identified"] is False
        assert entry["created_at"] is not None
        assert "distinct_ids" in entry
        assert "did-1" in entry["distinct_ids"]

    def test_distinct_ids_included(self):
        person = create_person(
            team=self.team,
            distinct_ids=["did-a", "did-b", "did-c"],
            properties={},
        )

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(person.uuid)])

        entry = result[str(person.uuid)]
        assert set(entry["distinct_ids"]) == {"did-a", "did-b", "did-c"}

    def test_distinct_ids_prefer_identified_over_anonymous(self):
        # The anonymous-looking ID is seeded first, but the identified one must come first in the
        # result so consumers reading distinct_ids[0] (person links, CSV exports) get the
        # human-readable ID rather than the auto-generated anonymous one.
        anonymous_id = "0190f8e1-1234-7abc-89de-f0123456789a"
        person = create_person(
            team=self.team,
            distinct_ids=[anonymous_id, "user@example.com"],
            properties={},
        )

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(person.uuid)])

        entry = result[str(person.uuid)]
        assert entry["distinct_ids"][0] == "user@example.com"
        assert set(entry["distinct_ids"]) == {anonymous_id, "user@example.com"}

    def test_multiple_persons(self):
        p1 = create_person(team=self.team, distinct_ids=["u1"], properties={"n": "1"})
        p2 = create_person(team=self.team, distinct_ids=["u2"], properties={"n": "2"})
        p3 = create_person(team=self.team, distinct_ids=["u3"], properties={"n": "3"})

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(p1.uuid), str(p2.uuid), str(p3.uuid)])

        assert len(result) == 3
        assert result[str(p1.uuid)]["properties"] == {"n": "1"}
        assert result[str(p2.uuid)]["properties"] == {"n": "2"}
        assert result[str(p3.uuid)]["properties"] == {"n": "3"}

    def test_missing_persons_excluded(self):
        person = create_person(team=self.team, distinct_ids=["real"], properties={})
        fake_uuid = str(uuid4())

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(person.uuid), fake_uuid])

        assert len(result) == 1
        assert str(person.uuid) in result
        assert fake_uuid not in result

    def test_empty_actor_ids(self):
        strategy = _make_strategy(self.team)
        result = strategy.get_actors([])

        assert result == {}

    def test_batching(self):
        persons = []
        for i in range(5):
            p = create_person(team=self.team, distinct_ids=[f"batch-{i}"], properties={"i": i})
            persons.append(p)

        strategy = _make_strategy(self.team)
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2):
            result = strategy.get_actors([str(p.uuid) for p in persons])

        assert len(result) == 5
        for p in persons:
            assert str(p.uuid) in result

    def test_sort_by_created_at_descending(self):
        now = timezone.now()
        p_old = create_person(team=self.team, distinct_ids=["old"], properties={})
        p_mid = create_person(team=self.team, distinct_ids=["mid"], properties={})
        p_new = create_person(team=self.team, distinct_ids=["new"], properties={})

        p_old.created_at = now - timedelta(hours=3)
        p_mid.created_at = now - timedelta(hours=1)
        p_new.created_at = now
        for p in [p_old, p_mid, p_new]:
            update_person(p)

        strategy = _make_strategy(self.team)
        result = strategy.get_actors(
            [str(p_old.uuid), str(p_mid.uuid), str(p_new.uuid)],
            sort_by_created_at_descending=True,
        )

        uuids_in_order = list(result.keys())
        assert uuids_in_order == [str(p_new.uuid), str(p_mid.uuid), str(p_old.uuid)]

    def test_cross_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_person = create_person(team=other_team, distinct_ids=["other"], properties={})
        own_person = create_person(team=self.team, distinct_ids=["own"], properties={})

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(own_person.uuid), str(other_person.uuid)])

        assert len(result) == 1
        assert str(own_person.uuid) in result
        assert str(other_person.uuid) not in result
