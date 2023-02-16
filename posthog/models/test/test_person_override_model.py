import contextlib
import datetime as dt
from uuid import uuid4
from django.db.utils import ConnectionHandler

import pytest
from django.db.utils import IntegrityError
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from posthog.models import PersonOverride, Team
from posthog.models.person.person import Person


from django.db.utils import DEFAULT_DB_ALIAS, load_backend


pytestmark = pytest.mark.django_db


@contextlib.contextmanager
def create_connection(alias=DEFAULT_DB_ALIAS):
    connection = ConnectionHandler().create_connection(alias)
    yield connection
    connection.close()


def test_person_override_disallows_same_old_person_id():
    """Test a new old_person_id cannot match an existing old_person_id.

    This is enforced by a UNIQUE constraint on (team_id, old_person_id)
    """
    organization = create_organization(name="test")
    team = create_team(organization=organization)

    oldest_event = dt.datetime.now(dt.timezone.utc)
    old_person_id = uuid4()
    override_person_id = uuid4()
    new_override_person_id = uuid4()

    Person.objects.create(
        team_id=team.pk,
        uuid=override_person_id,
    )

    person_override = PersonOverride.objects.create(
        team=team,
        old_person_id=old_person_id,
        override_person_id=override_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    person_override.save()

    assert person_override.old_person_id == old_person_id
    assert person_override.override_person_id == override_person_id

    Person.objects.create(
        team_id=team.pk,
        uuid=new_override_person_id,
    )

    with pytest.raises(IntegrityError):
        PersonOverride.objects.create(
            team=team,
            old_person_id=old_person_id,
            override_person_id=new_override_person_id,
            oldest_event=oldest_event,
            version=1,
        ).save()


def test_person_override_same_old_person_id_in_different_teams():
    """Test a new old_person_id can match an existing from a different team."""
    organization = create_organization(name="test")
    team = create_team(organization=organization)

    oldest_event = dt.datetime.now(dt.timezone.utc)
    old_person_id = uuid4()
    override_person_id = uuid4()
    new_team = Team.objects.create(
        organization=organization,
        api_token="a different token",
    )

    Person.objects.create(
        team_id=team.pk,
        uuid=override_person_id,
    )

    p1 = PersonOverride.objects.create(
        team=team,
        old_person_id=old_person_id,
        override_person_id=override_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    p1.save()

    assert p1.old_person_id == old_person_id
    assert p1.override_person_id == override_person_id

    p2 = PersonOverride.objects.create(
        team=new_team,
        old_person_id=old_person_id,
        override_person_id=override_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    p2.save()

    assert p1.old_person_id == p2.old_person_id
    assert p1.override_person_id == p2.override_person_id
    assert p1.team != p2.team


def test_person_override_allows_override_person_id_as_old_person_id_in_different_teams():
    """Test a new old_person_id can match an override in a different team."""
    organization = create_organization(name="test")
    team = create_team(organization=organization)

    oldest_event = dt.datetime.now(dt.timezone.utc)
    old_person_id = uuid4()
    override_person_id = uuid4()
    new_override_person_id = uuid4()
    new_team = Team.objects.create(
        organization=organization,
        api_token="a much different token",
    )

    Person.objects.create(
        team_id=team.pk,
        uuid=override_person_id,
    )

    p1 = PersonOverride.objects.create(
        team=team,
        old_person_id=old_person_id,
        override_person_id=override_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    p1.save()

    assert p1.old_person_id == old_person_id
    assert p1.override_person_id == override_person_id

    Person.objects.create(
        team_id=team.pk,
        uuid=new_override_person_id,
    )

    p2 = PersonOverride.objects.create(
        team=new_team,
        old_person_id=override_person_id,
        override_person_id=new_override_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    p2.save()

    assert p1.override_person_id == p2.old_person_id
    assert p2.override_person_id == new_override_person_id
    assert p1.team != p2.team


@pytest.mark.django_db(transaction=True)
def test_person_override_disallows_old_person_id_as_override_person_id():
    """Test a new override_person_id cannot match an existing old_person_id.

    We re-use the old_person_id from the first model created as the override_person_id
    of the second model. We expect an exception on saving this second model.

    Note that to test the race condition scenario we need to:

     1. create multiple concurrent transactions, such that we can verify
        constraints are enforced at COMMIT time.
     2. enable transactions for the Django test. This is more so we can see data
        from the main Django PostgreSQL connection session in the other
        concurrent transactions. Not 100% required but makes things a little
        easier to write.
    """
    organization = create_organization(name="test")
    team = create_team(organization=organization)

    oldest_event = dt.datetime.now(dt.timezone.utc)
    old_person_id = uuid4()
    override_person_id = uuid4()
    new_override_person_id = uuid4()

    Person.objects.create(uuid=old_person_id, team=team)
    Person.objects.create(uuid=override_person_id, team=team)
    Person.objects.create(uuid=new_override_person_id, team=team)

    with create_connection() as first_connection, first_connection.cursor() as first_cursor, create_connection() as second_connection, second_connection.cursor() as second_cursor:
        first_cursor.execute("BEGIN; SET lock_timeout TO '1s';")
        second_cursor.execute("BEGIN; SET lock_timeout TO '1s'; ")

        first_cursor.execute(
            """
                INSERT INTO posthog_personoverride
                (team_id, old_person_id, override_person_id, oldest_event, version)
                VALUES
                (%s, %s, %s, %s, %s)
            """,
            [team.pk, old_person_id, override_person_id, oldest_event, 1],
        )

        first_cursor.execute(
            """
                DELETE FROM posthog_person WHERE uuid = %s
            """,
            [old_person_id],
        )

        second_cursor.execute(
            """
                DELETE FROM posthog_person WHERE uuid = %s
            """,
            [override_person_id],
        )

        second_cursor.execute(
            """
                INSERT INTO posthog_personoverride
                (team_id, old_person_id, override_person_id, oldest_event, version)
                VALUES
                (%s, %s, %s, %s, %s)
            """,
            [team.pk, override_person_id, new_override_person_id, oldest_event, 1],
        )

        first_cursor.execute("COMMIT")

        with pytest.raises(IntegrityError):
            second_cursor.execute("COMMIT")

    assert list(PersonOverride.objects.all().values_list("old_person_id", "override_person_id")) == [
        (old_person_id, new_override_person_id),
    ]  # type: ignore


def test_person_override_old_person_id_as_override_person_id_in_different_teams():
    """Test a new override_person_id can match an old in a different team."""
    organization = create_organization(name="test")
    team = create_team(organization=organization)

    oldest_event = dt.datetime.now(dt.timezone.utc)
    old_person_id = uuid4()
    override_person_id = uuid4()
    new_old_person_id = uuid4()
    new_team = Team.objects.create(
        organization=organization,
        api_token="a significantly different token",
    )

    Person.objects.create(uuid=old_person_id, team=team)
    Person.objects.create(uuid=override_person_id, team=team)
    Person.objects.create(uuid=new_old_person_id, team=team)

    p1 = PersonOverride.objects.create(
        team=team,
        old_person_id=old_person_id,
        override_person_id=override_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    p1.save()

    assert p1.old_person_id == old_person_id
    assert p1.override_person_id == override_person_id

    p2 = PersonOverride.objects.create(
        team=new_team,
        old_person_id=new_old_person_id,
        override_person_id=old_person_id,
        oldest_event=oldest_event,
        version=1,
    )
    p2.save()

    assert p1.old_person_id == p2.override_person_id
    assert p2.old_person_id == new_old_person_id
    assert p1.team != p2.team


def test_person_override_allows_duplicate_override_person_id():
    """Test duplicate override_person_ids with different old_person_ids are allowed."""
    organization = create_organization(name="test")
    team = create_team(organization=organization)

    oldest_event = dt.datetime.now(dt.timezone.utc)
    override_person_id = uuid4()
    n_person_overrides = 2
    created = []

    Person.objects.create(uuid=override_person_id, team=team)

    for _ in range(n_person_overrides):
        old_person_id = uuid4()

        person_override = PersonOverride.objects.create(
            team=team,
            old_person_id=old_person_id,
            override_person_id=override_person_id,
            oldest_event=oldest_event,
            version=1,
        )
        person_override.save()

        created.append(person_override)

    assert all(p.override_person_id == override_person_id for p in created)
    assert len(set(p.old_person_id for p in created)) == n_person_overrides
