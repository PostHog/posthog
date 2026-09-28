from posthog.test.base import BaseTest

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.destination_mapping_secrets import find_mapping_secret_keys, move_mapping_secrets

SECRET_SCHEMA = {"key": "api_key", "type": "string", "label": "API key", "secret": True, "required": False}
URL_SCHEMA = {"key": "url", "type": "string", "label": "URL", "required": False}


def _mapping(name: str, api_key: str) -> dict:
    return {
        "name": name,
        "inputs_schema": [URL_SCHEMA, SECRET_SCHEMA],
        "inputs": {"url": {"value": f"https://example.com/{name}"}, "api_key": {"value": api_key}},
    }


class TestDestinationMappingSecrets(BaseTest):
    def _destination(self, inputs_schema: list[dict], mappings: list[dict]) -> HogFunction:
        hog_function = HogFunction.objects.create(team=self.team, name="destination", type="destination", hog="")
        # Written with `update` because these rows predate the rule that rejects secret mapping inputs.
        HogFunction.objects.filter(pk=hog_function.pk).update(inputs_schema=inputs_schema, inputs={}, mappings=mappings)
        return HogFunction.objects.get(pk=hog_function.pk)

    def test_moves_a_shared_secret_into_encrypted_inputs(self) -> None:
        hog_function = self._destination([], [_mapping("a", "key-1"), _mapping("b", "key-1")])

        keys = find_mapping_secret_keys(self.team.pk)
        assert [(k.function_id, k.key, k.movable) for k in keys] == [(str(hog_function.pk), "api_key", True)]
        assert move_mapping_secrets(keys) == 1

        hog_function.refresh_from_db()
        assert hog_function.encrypted_inputs == {"api_key": {"value": "key-1"}}
        assert "api_key" not in (hog_function.inputs or {})
        assert [(s["key"], s.get("secret")) for s in hog_function.inputs_schema or []] == [("api_key", True)]
        for mapping in hog_function.mappings or []:
            assert [s["key"] for s in mapping["inputs_schema"]] == ["url"]
            assert set(mapping["inputs"]) == {"url"}
        assert find_mapping_secret_keys(self.team.pk) == []

    def test_leaves_keys_that_cannot_move_without_changing_what_is_sent(self) -> None:
        differing = self._destination([], [_mapping("a", "key-1"), _mapping("b", "key-2")])
        clashing = self._destination([{**SECRET_SCHEMA, "secret": False}], [_mapping("a", "key-1")])
        stored = {h.pk: (h.inputs_schema, h.mappings) for h in (differing, clashing)}

        keys = find_mapping_secret_keys(self.team.pk)
        assert {(k.function_id, k.skip_reason) for k in keys} == {
            (str(differing.pk), "mappings store different values for this key"),
            (str(clashing.pk), "the destination inputs already use this key"),
        }
        assert move_mapping_secrets(keys) == 0
        assert {h.pk: (h.inputs_schema, h.mappings) for h in HogFunction.objects.filter(pk__in=stored)} == stored
