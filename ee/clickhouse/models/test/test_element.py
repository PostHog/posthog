import uuid

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.element import create_elements, get_all_elements, get_elements_by_elements_hash
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.base import BaseTest
from posthog.models import Element


class TestClickhouseElement(ClickhouseTestMixin, BaseTest):
    def test_create_elements(self) -> None:
        elements_hash_1 = create_elements(
            event_uuid=uuid.uuid4(),
            team=self.team,
            elements=[
                Element(tag_name="a", href="/a-url", nth_child=1, nth_of_type=0),
                Element(tag_name="button", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
            use_cache=False,
        )

        self.assertEqual(len(get_all_elements()), 4)

        elements_hash_2 = create_elements(
            event_uuid=uuid.uuid4(),
            team=self.team,
            elements=[
                Element(tag_name="a", href="/a-url", nth_child=1, nth_of_type=0),
                Element(tag_name="button", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
            use_cache=False,
        )

        self.assertEqual(elements_hash_1, elements_hash_2)

        self.assertGreater(len(get_all_elements(final=False)), 4)
        self.assertEqual(len(get_all_elements(final=True)), 4)

        elements = get_elements_by_elements_hash(elements_hash=elements_hash_1, team_id=self.team.pk)
        self.assertEqual(len(elements), 4)

        self.assertEqual(elements[0]["tag_name"], "a")
        self.assertEqual(elements[1]["tag_name"], "button")
        self.assertEqual(elements[2]["tag_name"], "div")
        self.assertEqual(elements[3]["tag_name"], "div")

        self.assertEqual(elements[0]["order"], 0)
        self.assertEqual(elements[1]["order"], 1)
        self.assertEqual(elements[2]["order"], 2)
        self.assertEqual(elements[3]["order"], 3)

        self.assertGreater(len(get_all_elements()), 4)
        sync_execute("OPTIMIZE TABLE elements FINAL")
        self.assertEqual(len(get_all_elements()), 4)

    def test_create_cache(self) -> None:
        self.assertEqual(len(get_all_elements()), 0)

        create_elements(
            event_uuid=uuid.uuid4(),
            team=self.team,
            elements=[
                Element(tag_name="a", href="/a-url", nth_child=1, nth_of_type=0),
                Element(tag_name="button", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
            use_cache=True,
        )

        self.assertEqual(len(get_all_elements()), 4)

        create_elements(
            event_uuid=uuid.uuid4(),
            team=self.team,
            elements=[
                Element(tag_name="a", href="/a-url", nth_child=1, nth_of_type=0),
                Element(tag_name="button", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
            use_cache=True,
        )

        self.assertEqual(len(get_all_elements()), 4)
