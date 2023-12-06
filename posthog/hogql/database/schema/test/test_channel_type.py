import uuid

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    ClickhouseDestroyTablesMixin,
)


class ReferringDomainTypeQueryRunner(ClickhouseDestroyTablesMixin, ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _get_initial_referring_domain_type(self, initial_referring_domain: str):
        person_id = str(uuid.uuid4())

        _create_person(
            uuid=person_id,
            team_id=self.team.pk,
            distinct_ids=[person_id],
            properties={
                "$initial_referring_domain": initial_referring_domain,
            },
        )

        response = execute_hogql_query(
            parse_select(
                "select $virt_initial_referring_domain_type as channel_type from persons where id = {person_id}",
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
        )

        return response.results[0][0]

    def test_direct(self):
        self.assertEqual(
            "$direct",
            self._get_initial_referring_domain_type("$direct"),
        )

    def test_search(self):
        self.assertEqual(
            "Search",
            self._get_initial_referring_domain_type("www.google.co.uk"),
        )
        self.assertEqual(
            "Search",
            self._get_initial_referring_domain_type("yahoo.co.jp"),
        )

    def test_shopping(self):
        self.assertEqual(
            "Shopping",
            self._get_initial_referring_domain_type("m.alibaba.com"),
        )
        self.assertEqual(
            "Shopping",
            self._get_initial_referring_domain_type("stripe.com"),
        )

    def test_social(self):
        self.assertEqual(
            "Social",
            self._get_initial_referring_domain_type("lnkd.in"),
        )
        self.assertEqual(
            "Social",
            self._get_initial_referring_domain_type("old.reddit.com"),
        )


class ChannelTypeQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _get_initial_channel_type(self, properties=None):
        person_id = str(uuid.uuid4())

        _create_person(
            uuid=person_id,
            team_id=self.team.pk,
            distinct_ids=[person_id],
            properties=properties,
        )

        response = execute_hogql_query(
            parse_select(
                "select $virt_initial_channel_type as channel_type from persons where id = {person_id}",
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
        )

        return response.results[0][0]

    def test_direct(self):
        self.assertEqual(
            "Direct",
            self._get_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                }
            ),
        )

    def test_cross_network(self):
        self.assertEqual(
            "Cross Network",
            self._get_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                    "$initial_utm_campaign": "cross-network",
                }
            ),
        )

    def test_paid_shopping(self):
        self.assertEqual(
            "Paid Shopping",
            self._get_initial_channel_type(
                {
                    "$initial_referring_domain": "www.ebay.co.uk",
                    "$initial_utm_medium": "ppc",
                }
            ),
        )

    def test_paid_search(self):
        self.assertEqual(
            "Paid Shopping",
            self._get_initial_channel_type(
                {
                    "$initial_referring_domain": "www.ebay.co.uk",
                    "$initial_utm_medium": "ppc",
                }
            ),
        )

    def test_paid_video(self):
        self.assertEqual(
            "Paid Video",
            self._get_initial_channel_type(
                {
                    "$initial_referring_domain": "youtube.com",
                    "$initial_utm_medium": "cpm",
                }
            ),
        )

    def test_organic_video(self):
        self.assertEqual(
            "Organic Video",
            self._get_initial_channel_type(
                {
                    "$initial_referring_domain": "youtube.com",
                }
            ),
        )
