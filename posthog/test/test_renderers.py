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
        response: dict = {}
        node = response
        for _ in range(300):
            node["values"] = [{}]
            node = node["values"][0]
        node["key"] = "platform"

        with patch("posthog.renderers.capture_exception") as mock_capture:
            data = SafeJSONRenderer().render(response)

        self.assertEqual(json.loads(data), response)
        mock_capture.assert_called_once()

    def test_still_raises_for_unserializable_payload(self):
        with self.assertRaises(TypeError):
            SafeJSONRenderer().render({"value": object()})
