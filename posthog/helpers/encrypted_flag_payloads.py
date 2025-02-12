from posthog.auth import PersonalAPIKeyAuthentication
from posthog.temporal.common.codec import EncryptionCodec
from django.conf import settings

REDACTED_PAYLOAD_VALUE = '"********* (encrypted)"'


def get_decrypted_flag_payloads(request, encrypted_payloads: dict) -> dict:
    # We only decode encrypted flag payloads if the request is made with a personal API key
    is_personal_api_request = isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication)

    codec = EncryptionCodec(settings)

    decrypted_payloads = {}
    for key, value in (encrypted_payloads or {}).items():
        decrypted_payloads[key] = (
            codec.decrypt(value.encode("utf-8")).decode("utf-8") if is_personal_api_request else REDACTED_PAYLOAD_VALUE
        )

    return decrypted_payloads


def encrypt_flag_payloads(validated_data: dict):
    if not validated_data.get("has_encrypted_payloads", False):
        return

    if "filters" not in validated_data:
        return

    if "payloads" not in validated_data["filters"]:
        return

    payloads = validated_data["filters"]["payloads"]

    codec = EncryptionCodec(settings)

    for key, value in payloads.items():
        try:
            payloads[key] = codec.encrypt(value.encode("utf-8")).decode("utf-8")
        except Exception as e:
            raise ValueError(f"Failed to encrypt payload for key {key}") from e
