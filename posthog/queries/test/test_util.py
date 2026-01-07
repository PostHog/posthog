from django.test import TestCase

from posthog.queries.util import correct_result_for_sampling


class TestQueriesUtil(TestCase):
    def test_correct_resullt_for_sampling(self):
        res = correct_result_for_sampling(1, 0.1, None)
        assert res == 10

        res = correct_result_for_sampling(1, 0.01, None)
        assert res == 100

        res = correct_result_for_sampling(1, None, None)
        assert res == 1

        res = correct_result_for_sampling(1, 0.01, "max")
        assert res == 1

        res = correct_result_for_sampling(1, 0.01, "p90_count_per_actor")
        assert res == 1

        res = correct_result_for_sampling(1, 0.01, "sum")
        assert res == 100
