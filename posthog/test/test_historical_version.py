import uuid

from django.db.utils import IntegrityError

from posthog.models import HistoricalVersion
from posthog.test.base import BaseTest


class TestHistoricalVersion(BaseTest):
    def test_can_save_if_there_is_a_team_id(self):
        try:
            HistoricalVersion.objects.create(team_id=3, state={})
        except Exception as e:
            self.fail(f"should not have raised {e}")

    def test_can_save_if_there_is_an_organisation_id(self):
        try:
            HistoricalVersion.objects.create(organization_id=uuid.uuid4(), state={})
        except Exception as e:
            self.fail(f"should not have raised {e}")

    def test_can_not_save_if_there_is_neither_a_team_id_nor_an_organisation_id(self):
        # even when there are versions with team id or org id saved
        HistoricalVersion.objects.create(team_id=3, state={})
        HistoricalVersion.objects.create(organization_id=uuid.uuid4(), state={})
        # we cannot save a new version if it has neither team nor org id
        with self.assertRaises(IntegrityError) as error:
            HistoricalVersion.objects.create(state={})

        self.assertIn(
            'new row for relation "posthog_historicalversion" violates check constraint "must_have_team_or_organization_id',
            error.exception.args[0],
        )
