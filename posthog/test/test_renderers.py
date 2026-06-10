import json

from django.test import TestCase

from parameterized import parameterized

from posthog.renderers import SafeJSONRenderer


class TestCleanDataForJSON(TestCase):
    def test_cleans_dict_with_nan_and_inf_scalars(self):
        response = {
            "control": 1.0,
            "test_1": float("nan"),
            "test_2": float("inf"),
        }
        data = SafeJSONRenderer().render(response)

        self.assertDictEqual(
            json.loads(data),
            {
                "control": 1.0,
                "test_1": None,
                "test_2": None,
            },
        )

    def test_cleans_dict_with_nan_and_inf_list(self):
        response = {
            "control": 1.0,
            "test": [float("inf"), 1.0, float("nan")],
        }
        data = SafeJSONRenderer().render(response)

        self.assertDictEqual(
            json.loads(data),
            {
                "control": 1.0,
                "test": [None, 1.0, None],
            },
        )

    def test_cleans_dict_with_nan_and_inf_tuple(self):
        response = {
            "control": 1.0,
            "test": (float("inf"), 1.0, float("nan")),
        }
        data = SafeJSONRenderer().render(response)

        self.assertDictEqual(
            json.loads(data),
            {
                "control": 1.0,
                "test": [None, 1.0, None],
            },
        )

    def test_cleans_dict_with_nan_and_inf_nested_list(self):
        response = {
            "control": 1.0,
            "test": [
                float("inf"),
                [float("inf"), float("nan"), 1.0],
                float("nan"),
                5.0,
            ],
        }
        data = SafeJSONRenderer().render(response)

        self.assertDictEqual(
            json.loads(data),
            {
                "control": 1.0,
                "test": [None, [None, None, 1.0], None, 5.0],
            },
        )

    @parameterized.expand(
        [
            ("utf8_bytes", b"hello", "hello"),
            ("non_utf8_bytes", b"\x80\x81\xff", "8081ff"),
        ]
    )
    def test_renders_bytes(self, _name, value, expected):
        data = SafeJSONRenderer().render({"value": value})

        self.assertEqual(json.loads(data), {"value": expected})

    def test_cleans_dict_with_nan_nested_dict(self):
        response = {
            "control": 1.0,
            "test": [{"yup": True, "meh": [], "nope": float("nan")}],
        }
        data = SafeJSONRenderer().render(response)

        self.assertDictEqual(
            json.loads(data),
            {
                "control": 1.0,
                "test": [
                    {
                        "yup": True,
                        "meh": [],
                        "nope": None,
                    }
                ],
            },
        )
