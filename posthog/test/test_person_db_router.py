import pytest

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import Organization
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person
from posthog.person_db_router import (
    PersonDBRouter,
    PersonsDBORMBlockedError,
    allow_persons_orm,
    block_persons_orm,
    unblock_persons_orm,
)


class TestPersonDBRouterGuard:
    """Unit tests for the router guard. Marked persons_db_direct to skip the autouse
    personhog fake so the block flag is controlled explicitly here, not by the fixture."""

    pytestmark = pytest.mark.persons_db_direct

    def setup_method(self):
        self.router = PersonDBRouter()
        unblock_persons_orm()

    def teardown_method(self):
        unblock_persons_orm()

    @parameterized.expand([("read", "db_for_read"), ("write", "db_for_write")])
    def test_routes_nothing_when_unblocked(self, _name, method):
        # The router never selects a database — its only job is to guard.
        assert getattr(self.router, method)(Person) is None
        assert getattr(self.router, method)(Organization) is None

    @parameterized.expand([("person", Person), ("group_type_mapping", GroupTypeMapping)])
    def test_blocked_persons_model_raises(self, _name, model):
        block_persons_orm()
        with pytest.raises(PersonsDBORMBlockedError):
            self.router.db_for_read(model)
        with pytest.raises(PersonsDBORMBlockedError):
            self.router.db_for_write(model)

    def test_blocked_non_persons_model_is_allowed(self):
        block_persons_orm()
        assert self.router.db_for_read(Organization) is None
        assert self.router.db_for_write(Organization) is None

    def test_fk_instance_hint_does_not_trip_block(self):
        # Django calls db_for_write with the *related* instance while resolving an FK
        # assignment (e.g. GroupTypeMapping(team=team)); nothing is being written, so the
        # guard must stay quiet.
        block_persons_orm()
        assert self.router.db_for_write(Person, instance=Organization(name="x")) is None

    def test_allow_persons_orm_temporarily_unblocks(self):
        block_persons_orm()
        with allow_persons_orm():
            assert self.router.db_for_read(Person) is None
        with pytest.raises(PersonsDBORMBlockedError):
            self.router.db_for_read(Person)

    def test_records_orm_access_metric(self):
        # The counter is the production canary — the block is off in prod, so a stray persons
        # ORM access must still be observable. Guards against the increment being dropped.
        labels = {"model": "person", "operation": "read"}
        before = REGISTRY.get_sample_value("posthog_persons_orm_access_total", labels) or 0.0
        self.router.db_for_read(Person)
        after = REGISTRY.get_sample_value("posthog_persons_orm_access_total", labels) or 0.0
        assert after == before + 1


@pytest.mark.django_db
class TestPersonsORMBlockedEndToEnd:
    """End-to-end: with the personhog fake active (the default autouse fixture), a real
    persons-model ORM query must raise rather than silently fall through to the main DB.

    This exercises the full wiring — fixture → block_persons_orm → router → is_persons_model
    — that the unit tests above stub out. The query raises during database selection, before
    any SQL runs.
    """

    @parameterized.expand(
        [
            ("person", lambda: Person.objects.filter(team_id=1).first()),
            ("group_type_mapping", lambda: list(GroupTypeMapping.objects.filter(project_id=1))),
        ]
    )
    def test_real_orm_query_raises_under_active_fake(self, _name, run_query):
        with pytest.raises(PersonsDBORMBlockedError):
            run_query()
