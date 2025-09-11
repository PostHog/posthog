# ruff: noqa
import importlib

from posthog.test.base import BaseTest, ClickhouseDestroyTablesMixin, _create_event
from posthog.clickhouse.client import sync_execute
from posthog.models.utils import UUIDT

module = importlib.import_module("posthog.clickhouse.migrations.0064_materialize_elements_chain")

add_columns_to_required_tables = module.add_columns_to_required_tables

from posthog.models.element.element import Element, chain_to_elements


def _create_events(team, elements_chains=[]):
    for ec in elements_chains:
        _create_event(
            team=team,
            distinct_id="1",
            event="$autocapture",
            elements=chain_to_elements(ec),
        )


class Test0064(ClickhouseDestroyTablesMixin):
    def test_filtering(self):
        add_columns_to_required_tables("")
        _create_events(
            self.team,
            [
                # should be extracted
                'a:attr_id="easy_text"',
                'a:attr_id="cutoff"text"',
                'a:something="else"attr_id="text3"',
                'a:attr_id="text4";b:attr_id="text5"',
                # don't extract
                'a:differentattr_id="text2"',
            ],
        )
        resp = sync_execute("select elements_chain_ids from events where elements_chain_ids[1] != ''")
        self.assertCountEqual(
            [row[0] for row in resp], [["easy_text"], ["cutoff"], ["text3"], ["text4", "text5"]], resp
        )
