"""Keep an encrypted flag payload out of a change request, both where it is stored and where it is served.

A gated flag write reaches the approval gate before `FeatureFlagSerializer` encrypts its payloads, so
the change the gate stores would otherwise hold them in the clear.
"""

import copy
from collections.abc import Iterator
from typing import Any, Optional

from products.approvals.backend.models import ChangeRequest
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE, flag_payload_codec
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Ciphertext for the payloads the stored change holds as the sentinel. The apply path writes it to the flag.
ENCRYPTED_PAYLOADS_KEY = "encrypted_payloads"
# Whether the stored change's payloads are secret, recorded beside the change so an apply never writes it.
PAYLOADS_ENCRYPTED_KEY = "payloads_encrypted"


def withhold_encrypted_payloads(intent: dict[str, Any], flag: Optional[FeatureFlag]) -> dict[str, Any]:
    """Return the intent with each secret payload replaced by the sentinel and its ciphertext kept beside it.

    The ciphertext cannot take the payload's place in the change, because filters validation requires every
    payload to be JSON and the apply path replays the change through that validation.
    """
    change = intent.get("full_request_data") or {}
    if not (change.get("filters") or {}).get("payloads"):
        return intent

    encrypted = bool(change.get("has_encrypted_payloads", flag.has_encrypted_payloads if flag is not None else False))
    intent = {**intent, PAYLOADS_ENCRYPTED_KEY: encrypted}
    if not encrypted:
        return intent

    codec = flag_payload_codec()
    change = copy.deepcopy(change)
    payloads = change["filters"]["payloads"]
    ciphertext = {}
    for key, value in payloads.items():
        # An echoed sentinel stands for the flag's stored ciphertext, which the apply path restores.
        if value != REDACTED_PAYLOAD_VALUE:
            ciphertext[key] = codec.encrypt(value.encode("utf-8")).decode("utf-8")
            payloads[key] = REDACTED_PAYLOAD_VALUE
    return {**intent, "full_request_data": change, ENCRYPTED_PAYLOADS_KEY: ciphertext}


def redact_secret_payloads(change_request: ChangeRequest, data: dict[str, Any]) -> dict[str, Any]:
    """Serve a change request without its ciphertext, and with every payload as the sentinel when they are secret.

    Copies before changing anything, because the serialized fields are the model's own dicts.
    """
    intent = data.get("intent")
    if isinstance(intent, dict) and ENCRYPTED_PAYLOADS_KEY in intent:
        data["intent"] = {key: value for key, value in intent.items() if key != ENCRYPTED_PAYLOADS_KEY}

    if change_request.resource_type != "feature_flag" or not _payloads_are_secret(change_request, data):
        return data

    for field in ("intent", "intent_display"):
        data[field] = copy.deepcopy(data.get(field))
        for payloads in _payload_maps(data[field]):
            for key in payloads:
                payloads[key] = REDACTED_PAYLOAD_VALUE
    return data


def _payloads_are_secret(change_request: ChangeRequest, data: dict[str, Any]) -> bool:
    if not any(_payload_maps(data.get("intent"))) and not any(_payload_maps(data.get("intent_display"))):
        return False

    intent = change_request.intent or {}
    if PAYLOADS_ENCRYPTED_KEY in intent:
        return intent[PAYLOADS_ENCRYPTED_KEY] is not False

    # A change request stored before the gate recorded its answer. The flag's current setting cannot answer for it,
    # because turning encryption off later would reveal a payload that was secret when it was stored. So it is
    # secret unless the change itself turned encryption off.
    change = intent.get("full_request_data") or {}
    return change.get("has_encrypted_payloads") is not False


def _payload_maps(value: Any) -> Iterator[dict[str, Any]]:
    """Every `payloads` mapping inside a stored change or its display, wherever the action put it."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "payloads" and isinstance(item, dict):
                yield item
            else:
                yield from _payload_maps(item)
    elif isinstance(value, list):
        for item in value:
            yield from _payload_maps(item)
