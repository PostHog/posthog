from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized_class

from posthog.schema import ActorsQuery

from posthog.hogql_queries.actor_strategies import PersonStrategy
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team
from posthog.personhog_client.test_helpers import PersonhogTestMixin


def _make_strategy(team) -> PersonStrategy:
    query = ActorsQuery(kind="ActorsQuery", select=["person"])
    paginator = HogQLHasMorePaginator(limit=100, offset=0)
    return PersonStrategy(team=team, query=query, paginator=paginator)


@parameterized_class(("personhog",), [(False,), (True,)])
class TestPersonStrategyGetActors(PersonhogTestMixin, BaseTest):
    def test_basic_person_lookup(self):
        person = self._seed_person(
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

        self._assert_personhog_called("get_persons_by_uuids")
        self._assert_personhog_called("get_distinct_ids_for_persons")

    def test_distinct_ids_included(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-a", "did-b", "did-c"],
            properties={},
        )

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(person.uuid)])

        entry = result[str(person.uuid)]
        assert set(entry["distinct_ids"]) == {"did-a", "did-b", "did-c"}

    def test_multiple_persons(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["u1"], properties={"n": "1"})
        p2 = self._seed_person(team=self.team, distinct_ids=["u2"], properties={"n": "2"})
        p3 = self._seed_person(team=self.team, distinct_ids=["u3"], properties={"n": "3"})

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(p1.uuid), str(p2.uuid), str(p3.uuid)])

        assert len(result) == 3
        assert result[str(p1.uuid)]["properties"] == {"n": "1"}
        assert result[str(p2.uuid)]["properties"] == {"n": "2"}
        assert result[str(p3.uuid)]["properties"] == {"n": "3"}

    def test_missing_persons_excluded(self):
        person = self._seed_person(team=self.team, distinct_ids=["real"], properties={})
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
            p = self._seed_person(team=self.team, distinct_ids=[f"batch-{i}"], properties={"i": i})
            persons.append(p)

        strategy = _make_strategy(self.team)
        with patch.object(PersonStrategy, "BATCH_SIZE", 2):
            result = strategy.get_actors([str(p.uuid) for p in persons])

        assert len(result) == 5
        for p in persons:
            assert str(p.uuid) in result

    def test_sort_by_created_at_descending(self):
        now = timezone.now()
        p_old = self._seed_person(team=self.team, distinct_ids=["old"], properties={})
        p_mid = self._seed_person(team=self.team, distinct_ids=["mid"], properties={})
        p_new = self._seed_person(team=self.team, distinct_ids=["new"], properties={})

        from posthog.models.person import Person

        Person.objects.filter(pk=p_old.pk).update(created_at=now - timedelta(hours=3))
        Person.objects.filter(pk=p_mid.pk).update(created_at=now - timedelta(hours=1))
        Person.objects.filter(pk=p_new.pk).update(created_at=now)

        if self._fake_client is not None:
            self._fake_client._persons_by_uuid[(self.team.pk, str(p_old.uuid))].created_at = int(
                (now - timedelta(hours=3)).timestamp() * 1000
            )
            self._fake_client._persons_by_uuid[(self.team.pk, str(p_mid.uuid))].created_at = int(
                (now - timedelta(hours=1)).timestamp() * 1000
            )
            self._fake_client._persons_by_uuid[(self.team.pk, str(p_new.uuid))].created_at = int(now.timestamp() * 1000)

        strategy = _make_strategy(self.team)
        result = strategy.get_actors(
            [str(p_old.uuid), str(p_mid.uuid), str(p_new.uuid)],
            sort_by_created_at_descending=True,
        )

        uuids_in_order = list(result.keys())
        assert uuids_in_order == [str(p_new.uuid), str(p_mid.uuid), str(p_old.uuid)]

    def test_cross_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_person = self._seed_person(team=other_team, distinct_ids=["other"], properties={})
        own_person = self._seed_person(team=self.team, distinct_ids=["own"], properties={})

        strategy = _make_strategy(self.team)
        result = strategy.get_actors([str(own_person.uuid), str(other_person.uuid)])

        assert len(result) == 1
        assert str(own_person.uuid) in result
        assert str(other_person.uuid) not in result
