from django.test import TestCase

from posthog.renderers import clean_data_for_json


class TestCleanDataForJSON(TestCase):
    def test_cleans_dict_with_nan_and_inf_scalars(self):
        data = {
            "control": 1.0,
            "test_1": float("nan"),
            "test_2": float("inf"),
        }
        top_level_markers = clean_data_for_json(data)

        self.assertEqual(top_level_markers, (False, False))
        self.assertDictEqual(
            data,
            {
                "control": 1.0,
                "test_1": None,
                "test_1::nan": True,
                "test_2": None,
                "test_2::inf": True,
            },
        )

    def test_cleans_dict_with_nan_and_inf_list(self):
        data = {
            "control": 1.0,
            "test": [float("inf"), 1.0, float("nan")],
        }
        top_level_markers = clean_data_for_json(data)

        self.assertEqual(top_level_markers, (False, False))
        self.assertDictEqual(
            {
                "control": 1.0,
                "test": [None, 1.0, None],
                "test::nan": {2: True},
                "test::inf": {0: True},
            },
            data,
        )

    def test_cleans_dict_with_nan_and_inf_nested_list(self):
        data = {
            "control": 1.0,
            "test": [
                float("inf"),
                [float("inf"), float("nan"), 1.0],
                float("nan"),
                5.0,
            ],
        }
        top_level_markers = clean_data_for_json(data)

        self.assertEqual(top_level_markers, (False, False))
        self.assertDictEqual(
            {
                "control": 1.0,
                "test": [None, [None, None, 1.0], None, 5.0],
                "test::nan": {1: {1: True}, 2: True},
                "test::inf": {0: True, 1: {0: True}},
            },
            data,
        )

    def test_cleans_dict_with_nan_nested_dict(self):
        data = {
            "control": 1.0,
            "test": [{"yup": True, "meh": [], "nope": float("nan")}],
        }
        top_level_markers = clean_data_for_json(data)

        self.assertEqual(top_level_markers, (False, False))
        self.assertDictEqual(
            {
                "control": 1.0,
                "test": [{"yup": True, "meh": [], "nope": None, "nope::nan": True}],
            },
            data,
        )
