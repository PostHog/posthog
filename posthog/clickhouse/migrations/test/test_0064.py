# ruff: noqa
import importlib

from posthog.test.base import BaseTest, ClickhouseDestroyTablesMixin, _create_event
from posthog.client import sync_execute
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
                'a:text="easy_text"',
                'a:text="cutoff"text"',
                'a:something="else"text="text3"',
                'a:text="text4";b:text="text5"',
                # don't extract
                'a:differentattr-text="text2"',
            ],
        )
        resp = sync_execute("select elements_chain_texts from events where elements_chain_texts[1] != ''")
        self.assertCountEqual(
            [row[0] for row in resp], [["easy_text"], ["cutoff"], ["text3"], ["text4", "text5"]], resp
        )

    def test_elements(self):
        add_columns_to_required_tables("")
        _create_events(
            self.team,
            [
                # should be extracted
                'a:text="easy_text";span:text="bla"',
                'a:text="cutoff"text";a:text="text"',
                'a:something="else"text="text3"',
                'span:text="text4";a:text="text5"',
                # don't extract
                'b:differentattr-text="text2"',
            ],
        )
        resp = sync_execute("select elements_chain_elements from events where length(elements_chain_elements) > 0")
        self.assertCountEqual(
            [row[0] for row in resp],
            [
                ["a"],
                ["a"],
                ["a"],
                ["a"],
            ],
            resp,
        )
