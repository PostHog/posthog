# Test cases for test-class-takes-an-unused-database.
# ruff: noqa
from django.test import SimpleTestCase

from posthog.test.base import APIBaseTest, BaseTest


# ruleid: test-class-takes-an-unused-database
class TestPureAssertions(BaseTest):
    def test_adds(self) -> None:
        assert 1 + 1 == 2


# ruleid: test-class-takes-an-unused-database
class TestPureApiHelper(APIBaseTest):
    def test_builds_a_url(self) -> None:
        assert build_url("a") == "/a"


# ok: test-class-takes-an-unused-database
class TestReadsATeam(BaseTest):
    def test_uses_the_fixture(self) -> None:
        assert self.team.name


# ok: test-class-takes-an-unused-database
class TestQueriesAModel(BaseTest):
    def test_counts_rows(self) -> None:
        assert Insight.objects.count() == 0


# ok: test-class-takes-an-unused-database
class TestCallsTheApi(APIBaseTest):
    def test_returns_ok(self) -> None:
        assert self.client.get("/api/insight").status_code == 200


# ok: test-class-takes-an-unused-database
class TestBuildsAFixture(BaseTest):
    def test_uses_a_helper(self) -> None:
        assert create_insight(name="x").name == "x"


# ok: test-class-takes-an-unused-database
class TestAlreadyDatabaseFree(SimpleTestCase):
    def test_adds(self) -> None:
        assert 1 + 1 == 2
