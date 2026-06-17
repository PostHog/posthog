import json
from urllib.parse import unquote

from unittest import TestCase

from parameterized import parameterized

from products.customer_analytics.backend.account_urls import build_account_deeplink


def _decode_open(url: str) -> dict:
    base, _, fragment = url.partition("#")
    assert base == "/customer_analytics/accounts"
    assert fragment.startswith("open=")
    return json.loads(unquote(fragment[len("open=") :]))


class TestBuildAccountDeeplink(TestCase):
    def test_id_only(self):
        assert _decode_open(build_account_deeplink(account_id="acc-1")) == {"id": "acc-1"}

    def test_all_fields(self):
        url = build_account_deeplink(account_id="acc-1", external_id="ext-1", name="Acme Corp", tab="usage")
        assert _decode_open(url) == {"id": "acc-1", "externalId": "ext-1", "name": "Acme Corp", "tab": "usage"}

    @parameterized.expand([("external_id", None), ("name", ""), ("tab", None)])
    def test_falsy_optionals_are_omitted(self, field, value):
        url = build_account_deeplink(account_id="acc-1", **{field: value})
        assert _decode_open(url) == {"id": "acc-1"}

    def test_name_with_special_characters_round_trips(self):
        url = build_account_deeplink(account_id="acc-1", name="Acme & Sons, Inc.")
        assert _decode_open(url) == {"id": "acc-1", "name": "Acme & Sons, Inc."}
