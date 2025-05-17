from ee.hogai.summarizers.utils import Summarizer
from posthog.test.base import BaseTest


class TestSummarizerUtils(BaseTest):
    def test_pluralize(self):
        assert Summarizer.pluralize("person", 1) == "person"
        assert Summarizer.pluralize("person", 2) == "persons"
