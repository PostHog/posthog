from posthog.models import Event, Person
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.test.trends import all_trend_tests
from posthog.queries.test.trends.base import QueryTest
from posthog.queries.trends import Trends
from posthog.test.base import TransactionBaseTest


# TODO: add more supported entities here
def setup_test(team: Team, payload):
    for entity, data in payload.items():
        if entity == "events":
            for event_data in data:
                Event.objects.create(team=team, **event_data)
        if entity == "people":
            for person_data in data:
                Person.objects.create(team=team, **person_data)


# ref: https://stackoverflow.com/questions/32899/how-do-you-generate-dynamic-parameterized-unit-tests-in-python
# need to generate tests without using subtest so that the transactions will be cleared after each test
class TestSequenceMeta(type):
    def __new__(mcs, name, bases, dict):
        def generate_test(new_test: QueryTest):
            def test(self):
                setup_test(self.team, new_test.data)
                res = Trends().run(Filter(data=new_test.filter_data), self.team)
                self.assertEqual(res, new_test.result)

            return test

        for new_test in all_trend_tests:
            test_name = "test_%s" % new_test.name
            dict[test_name] = generate_test(new_test)
        return type.__new__(mcs, name, bases, dict)


class TestTrendsCombos(TransactionBaseTest, metaclass=TestSequenceMeta):
    pass
