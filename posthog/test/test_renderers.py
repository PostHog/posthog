import json

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.renderers import SafeJSONRenderer


class TestCleanDataForJSON(SimpleTestCase):
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

    def test_renders_payload_nested_deeper_than_orjson_allows(self):
        def nested(leaf: dict) -> dict:
            root: dict = {}
            node = root
            for _ in range(300):
                node["values"] = [{}]
                node = node["values"][0]
            node.update(leaf)
            return root

        with patch("posthog.renderers.capture_exception") as mock_capture:
            data = SafeJSONRenderer().render(nested({"key": "platform", "value": float("nan")}))

        self.assertEqual(json.loads(data), nested({"key": "platform", "value": None}))
        mock_capture.assert_called_once()

    @parameterized.expand(
        [
            ("uint128", 2**100, str(2**100)),
            ("negative_int128", -(2**100), str(-(2**100))),
            ("largest_uint64_stays_a_number", 2**64 - 1, 2**64 - 1),
            ("smallest_int64_stays_a_number", -(2**63), -(2**63)),
            ("bool_untouched", True, True),
        ]
    )
    def test_renders_integers_wider_than_64_bits_as_strings(self, _, wide_value, expected):
        response = {
            "columns": ["session_id_v7", "count"],
            "results": [(wide_value, 1), [2**127, float("nan")]],
            "nested": {"id": 2**64},
        }

        data = SafeJSONRenderer().render(response)

        self.assertEqual(
            json.loads(data),
            {
                "columns": ["session_id_v7", "count"],
                "results": [[expected, 1], [str(2**127), None]],
                "nested": {"id": str(2**64)},
            },
        )

    def test_unserializable_payload_raises_without_the_fallback(self):
        with patch("posthog.renderers.capture_exception") as mock_capture, self.assertRaises(TypeError):
            SafeJSONRenderer().render({"value": object()})

        mock_capture.assert_not_called()
