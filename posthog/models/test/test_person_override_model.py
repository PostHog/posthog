import datetime as dt
from uuid import uuid4

import pytest
from django.db import connection
from django.db.utils import IntegrityError

from posthog.models import PersonOverride, PersonOverrideMapping, Team
from posthog.test.base import BaseTest


class TestPersonOverride(BaseTest):
    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)

        PersonOverride.objects.all().delete()
        PersonOverrideMapping.objects.all().delete()

        with connection.cursor() as cursor:
            # Constraints are all deferred during normal execution, but for testing we want them to fail
            # during the test cases to properly assert exceptions raised by constraint failures.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_person_override_disallows_same_old_person_id(self):
        """Test a new old_person_id cannot match an existing old_person_id.

        This is enforced by a UNIQUE constraint on (team_id, old_person_id)
        """
        oldest_event = dt.datetime.now(dt.timezone.utc)
        old_person_id = uuid4()
        override_person_id = uuid4()
        new_override_person_id = uuid4()

        old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=old_person_id,
        )
        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )
        person_override = PersonOverride.objects.create(
            team=self.team,
            old_person_id=old_mapping,
            override_person_id=override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        person_override.save()

        assert person_override.old_person_id == old_mapping
        assert person_override.override_person_id == override_mapping

        new_override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=new_override_person_id,
        )

        with pytest.raises(IntegrityError):
            PersonOverride.objects.create(
                team=self.team,
                old_person_id=old_mapping,
                override_person_id=new_override_mapping,
                oldest_event=oldest_event,
                version=1,
            ).save()

    def test_person_override_same_old_person_id_in_different_teams(self):
        """Test a new old_person_id can match an existing from a different team."""
        oldest_event = dt.datetime.now(dt.timezone.utc)
        old_person_id = uuid4()
        override_person_id = uuid4()
        new_team = Team.objects.create(
            organization=self.organization,
            api_token="a different token",
        )

        old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=old_person_id,
        )
        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )

        p1 = PersonOverride.objects.create(
            team=self.team,
            old_person_id=old_mapping,
            override_person_id=override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        p1.save()

        assert p1.old_person_id == old_mapping
        assert p1.override_person_id == override_mapping

        new_team_old_mapping = PersonOverrideMapping.objects.create(
            team_id=new_team.id,
            uuid=old_person_id,
        )
        new_team_override_mapping = PersonOverrideMapping.objects.create(
            team_id=new_team.id,
            uuid=override_person_id,
        )

        p2 = PersonOverride.objects.create(
            team=new_team,
            old_person_id=new_team_old_mapping,
            override_person_id=new_team_override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        p2.save()

        assert p1.old_person_id.uuid == p2.old_person_id.uuid
        assert p1.override_person_id.uuid == p2.override_person_id.uuid
        assert p1.old_person_id.id != p2.old_person_id.id
        assert p1.override_person_id.id != p2.override_person_id.id
        assert p1.team != p2.team

    def test_person_override_disallows_override_person_id_as_old_person_id(self):
        """Test a new old_person_id cannot match an existing override_person_id.

        We re-use the override_person_id from the first model created as the old_person_id
        of the second model. We expect an exception on saving this second model.
        """
        oldest_event = dt.datetime.now(dt.timezone.utc)
        old_person_id = uuid4()
        override_person_id = uuid4()
        new_override_person_id = uuid4()

        old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=old_person_id,
        )
        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )

        person_override = PersonOverride.objects.create(
            team=self.team,
            old_person_id=old_mapping,
            override_person_id=override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        person_override.save()

        assert person_override.old_person_id == old_mapping
        assert person_override.override_person_id == override_mapping

        new_override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=new_override_person_id,
        )

        with pytest.raises(IntegrityError):
            PersonOverride.objects.create(
                team=self.team,
                old_person_id=override_mapping,
                override_person_id=new_override_mapping,
                oldest_event=oldest_event,
                version=1,
            ).save()

    def test_person_override_allows_override_person_id_as_old_person_id_in_different_teams(self):
        """Test a new old_person_id can match an override in a different team."""
        oldest_event = dt.datetime.now(dt.timezone.utc)
        old_person_id = uuid4()
        override_person_id = uuid4()
        new_override_person_id = uuid4()
        new_team = Team.objects.create(
            organization=self.organization,
            api_token="a much different token",
        )

        old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=old_person_id,
        )
        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )

        p1 = PersonOverride.objects.create(
            team=self.team,
            old_person_id=old_mapping,
            override_person_id=override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        p1.save()

        assert p1.old_person_id == old_mapping
        assert p1.override_person_id == override_mapping

        new_team_old_mapping = PersonOverrideMapping.objects.create(
            team_id=new_team.id,
            uuid=override_person_id,
        )
        new_team_override_mapping = PersonOverrideMapping.objects.create(
            team_id=new_team.id,
            uuid=new_override_person_id,
        )
        p2 = PersonOverride.objects.create(
            team=new_team,
            old_person_id=new_team_old_mapping,
            override_person_id=new_team_override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        p2.save()

        assert p1.override_person_id.uuid == p2.old_person_id.uuid
        assert p2.override_person_id == new_team_override_mapping
        assert p1.team != p2.team

    def test_person_override_disallows_old_person_id_as_override_person_id(self):
        """Test a new override_person_id cannot match an existing old_person_id.

        We re-use the old_person_id from the first model created as the override_person_id
        of the second model. We expect an exception on saving this second model.
        """
        oldest_event = dt.datetime.now(dt.timezone.utc)
        old_person_id = uuid4()
        override_person_id = uuid4()
        new_old_person_id = uuid4()

        old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=old_person_id,
        )
        old_mapping.save()

        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )
        override_mapping.save()

        person_override = PersonOverride.objects.create(
            team=self.team,
            old_person_id=old_mapping,
            override_person_id=override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        person_override.save()

        assert person_override.old_person_id == old_mapping
        assert person_override.override_person_id == override_mapping

        new_old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=new_old_person_id,
        )
        new_old_mapping.save()

        with pytest.raises(IntegrityError):
            p = PersonOverride.objects.create(
                team=self.team,
                old_person_id=new_old_mapping,
                override_person_id=old_mapping,
                oldest_event=oldest_event,
                version=1,
            )
            p.save()

    def test_person_override_old_person_id_as_override_person_id_in_different_teams(self):
        """Test a new override_person_id can match an old in a different team."""
        oldest_event = dt.datetime.now(dt.timezone.utc)
        old_person_id = uuid4()
        override_person_id = uuid4()
        new_old_person_id = uuid4()
        new_team = Team.objects.create(
            organization=self.organization,
            api_token="a significantly different token",
        )

        old_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=old_person_id,
        )
        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )

        p1 = PersonOverride.objects.create(
            team=self.team,
            old_person_id=old_mapping,
            override_person_id=override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        p1.save()

        assert p1.old_person_id == old_mapping
        assert p1.override_person_id == override_mapping

        new_old_mapping = PersonOverrideMapping.objects.create(
            team_id=new_team.id,
            uuid=new_old_person_id,
        )
        new_override_mapping = PersonOverrideMapping.objects.create(
            team_id=new_team.id,
            uuid=old_mapping.uuid,
        )

        p2 = PersonOverride.objects.create(
            team=new_team,
            old_person_id=new_old_mapping,
            override_person_id=new_override_mapping,
            oldest_event=oldest_event,
            version=1,
        )
        p2.save()

        assert p1.old_person_id.uuid == p2.override_person_id.uuid
        assert p1.old_person_id.team_id == p1.override_person_id.team_id
        assert p2.old_person_id == new_old_mapping
        assert p1.team != p2.team

    def test_person_override_allows_duplicate_override_person_id(self):
        """Test duplicate override_person_ids with different old_person_ids are allowed."""
        oldest_event = dt.datetime.now(dt.timezone.utc)
        override_person_id = uuid4()
        n_person_overrides = 2
        created = []

        override_mapping = PersonOverrideMapping.objects.create(
            team_id=self.team.id,
            uuid=override_person_id,
        )

        for _ in range(n_person_overrides):
            old_person_id = uuid4()
            old_mapping = PersonOverrideMapping.objects.create(
                team_id=self.team.id,
                uuid=old_person_id,
            )

            person_override = PersonOverride.objects.create(
                team=self.team,
                old_person_id=old_mapping,
                override_person_id=override_mapping,
                oldest_event=oldest_event,
                version=1,
            )
            person_override.save()

            created.append(person_override)

        assert all(p.override_person_id == override_mapping for p in created)
        assert len(set(p.old_person_id.uuid for p in created)) == n_person_overrides
