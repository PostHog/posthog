from django.test import TestCase

from posthog.queries.util import correct_result_for_sampling


class TestQueriesUtil(TestCase):
    def test_correct_resullt_for_sampling(self):
        res = correct_result_for_sampling(1, 0.1, None)
        self.assertEqual(res, 10)

        res = correct_result_for_sampling(1, 0.01, None)
        self.assertEqual(res, 100)

        res = correct_result_for_sampling(1, None, None)
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "max")
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "p90_count_per_actor")
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "sum")
        self.assertEqual(res, 100)
