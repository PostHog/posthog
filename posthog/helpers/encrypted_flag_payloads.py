from posthog.auth import PersonalAPIKeyAuthentication
from posthog.temporal.common.codec import EncryptionCodec
from django.conf import settings

REDACTED_PAYLOAD_VALUE = '"********* (encrypted)"'


def get_decrypted_flag_payloads(request, encrypted_payloads: dict) -> dict:
    # We only decode encrypted flag payloads if the request is made with a personal API key
    is_personal_api_request = isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication)

    decrypted_payloads = {}
    for key, value in (encrypted_payloads or {}).items():
        decrypted_payloads[key] = get_decrypted_flag_payload(value, should_decrypt=is_personal_api_request)

    return decrypted_payloads


def get_decrypted_flag_payload(encrypted_payload: str | object, should_decrypt: bool) -> str:
    codec = EncryptionCodec(settings)
    return (
        codec.decrypt(str(encrypted_payload).encode("utf-8")).decode("utf-8")
        if should_decrypt
        else REDACTED_PAYLOAD_VALUE
    )


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


def encrypt_webhook_payloads(validated_data: dict):
    """
    Encrypts all string fields in webhook_subscriptions array except for 'url'.

    Structure:
    [
        {
            "url": "https://example.com/webhook",  # NOT encrypted
            "headers": {
                "Authorization": "Bearer token",  # encrypted
                "X-Custom": "value"  # encrypted
            }
        }
    ]
    """
    webhook_subscriptions = validated_data.get("webhook_subscriptions")

    if not webhook_subscriptions or not isinstance(webhook_subscriptions, list):
        return

    codec = EncryptionCodec(settings)

    for subscription in webhook_subscriptions:
        if not isinstance(subscription, dict):
            continue

        # Encrypt headers values
        for key, value in subscription.items():
            if key == "headers" and isinstance(value, dict):
                _encrypt_dict_values(value, codec)


def _encrypt_dict_values(data: dict, codec: EncryptionCodec):
    """Helper function to encrypt all string values in a dictionary."""
    for key, value in data.items():
        if isinstance(value, str):
            try:
                data[key] = codec.encrypt(value.encode("utf-8")).decode("utf-8")
            except Exception as e:
                raise ValueError(f"Failed to encrypt dict field '{key}'") from e
