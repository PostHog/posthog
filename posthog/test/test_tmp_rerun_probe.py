import unittest

_ATTEMPTS = {"plain": 0, "subtest": 0}


class TestTmpRerunProbe(unittest.TestCase):
    def test_plain_failure_passes_on_rerun(self):
        _ATTEMPTS["plain"] += 1
        self.assertGreater(_ATTEMPTS["plain"], 1)

    def test_subtest_failure_passes_on_rerun(self):
        _ATTEMPTS["subtest"] += 1
        for i in range(3):
            with self.subTest(i=i):
                self.assertTrue(_ATTEMPTS["subtest"] > 1 or i != 1)
