import unittest

from dateutil import parser

from posthog.models import Person, Team, User
from posthog.models.activity_logging.activity_log import changes_between
from posthog.models.utils import UUIDT


class TestChangesBetweenPersons(unittest.TestCase):
    def test_can_exclude_changed_fields_in_persons(self) -> None:
        actual = changes_between(
            model_type="Person",
            previous=self._a_person_with(
                id="before",
                uuid="before",
                distinct_ids="before",
                created_at="before",
                is_identified=True,
                properties={"a": "b"},
            ),
            current=self._a_person_with(
                id="after",
                uuid="after",
                distinct_ids="after",
                created_at="after",
                is_identified=False,
                properties={"a": "c"},
            ),
        )
        self.assertEqual([change.field for change in actual], ["properties"])

    @staticmethod
    def _a_person_with(**kwargs) -> Person:
        return Person(
            id=kwargs.get("id", 2),
            created_at=kwargs.get("created_at", parser.parse("12th April 2003")),
            properties_last_updated_at=kwargs.get("properties_last_updated_at", parser.parse("12th April 2003")),
            properties_last_operation=kwargs.get("properties_last_operation", {}),
            team=kwargs.get("team", Team()),
            properties=kwargs.get("properties", {}),
            is_user=kwargs.get("is_user", User()),
            is_identified=kwargs.get("is_identified", True),
            uuid=kwargs.get("uuid", UUIDT()),
            version=kwargs.get("version", 1),
        )
