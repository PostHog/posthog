from posthog.auth import PersonalAPIKeyAuthentication
from posthog.temporal.common.codec import EncryptionCodec
from django.conf import settings


def get_decrypted_flag_payloads(request, filters: dict) -> dict:
    # We only decode encrypted flag payloads if the request is made with a personal API key
    is_personal_api_request = isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication)

    codec = EncryptionCodec(settings)

    for key, value in filters.get("payloads", {}).items():
        filters["payloads"][key] = (
            codec.decrypt(value.encode("utf-8")).decode("utf-8") if is_personal_api_request else "********* (encrypted)"
        )

    return filters


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
        payloads[key] = codec.encrypt(value.encode("utf-8")).decode("utf-8")
