import json

from unittest.mock import patch

from django.test import SimpleTestCase

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

    def test_unserializable_payload_raises_without_the_fallback(self):
        with patch("posthog.renderers.capture_exception") as mock_capture, self.assertRaises(TypeError):
            SafeJSONRenderer().render({"value": object()})

        mock_capture.assert_not_called()
