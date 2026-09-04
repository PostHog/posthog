import json
import base64
import hashlib

import pytest
from unittest.mock import patch

from django.test import Client, override_settings

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from posthoganalytics.contexts import get_capture_exception_code_variables_context

from posthog.web_bot_auth import CONTENT_TYPE, jwk_thumbprint, public_jwk, signature_base, signed_directory
from posthog.web_bot_auth_keys import (
    WebBotAuthPrivateKeyConfigurationError,
    load_web_bot_auth_private_key_configuration,
    validate_web_bot_auth_private_keys_in_background,
)

PEM = (
    Ed25519PrivateKey.generate()
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)
NON_ED25519_PEM = (
    ec.generate_private_key(ec.SECP256R1())
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)


def dictionary_member(header: str, label: str) -> str:
    return next(member.removeprefix(f"{label}=") for member in header.split(", ") if member.startswith(f"{label}="))


def verify_at(authority: str, headers: dict[str, str], key: Ed25519PrivateKey, label: str = "sig1") -> bool:
    params = dictionary_member(headers["Signature-Input"], label)
    base = (
        f'"@authority";req: {authority}\n"content-digest": {headers["Content-Digest"]}\n"@signature-params": {params}'
    )
    signature = base64.b64decode(dictionary_member(headers["Signature"], label).removeprefix(":").removesuffix(":"))
    try:
        key.public_key().verify(signature, base.encode())
    except InvalidSignature:
        return False
    return True


def test_thumbprint_matches_the_rfc_8037_vector():
    # A thumbprint over the wrong members, or with spaces in the JSON, produces a keyid that no
    # verifier can match to the published key, and nothing else in the response looks wrong.
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"}

    assert jwk_thumbprint(jwk) == "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"


def test_the_directory_names_the_key_it_is_signed_with():
    key = serialization.load_pem_private_key(PEM.encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)

    body, headers = signed_directory([key], 1750105829, "AAAA")

    assert json.loads(body)["keys"] == [public_jwk(key)]
    assert f'keyid="{jwk_thumbprint(public_jwk(key))}"' in headers["Signature-Input"]


@pytest.mark.parametrize(
    "authority,expected",
    [("us.posthog.com", True), ("evil.example", False), ("posthog.com", False)],
)
def test_the_signature_only_verifies_at_the_authority_it_covers(authority: str, expected: bool):
    # This is the whole point of signing the directory. If the signature verified wherever the
    # response was served, any site that proxies this route would hold a directory that verifies on
    # that site while carrying our key, and could register as its operator.
    key = serialization.load_pem_private_key(PEM.encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)

    _, headers = signed_directory([key], 1750105829, "AAAA")

    assert verify_at(authority, headers, key) is expected


def test_the_signature_covers_the_parameters_it_publishes():
    # The base and the header are built together for this reason: a mismatch in one character makes
    # every signature fail verification while both halves look correct on their own.
    signature_base_value = signature_base("thumb", "AAAA", 1750105829, "sha-256=:AAAA:")

    assert signature_base_value.value.endswith(f'"@signature-params": {signature_base_value.parameters}')
    assert signature_base_value.parameters.startswith('("@authority";req "content-digest")')
    assert 'tag="http-message-signatures-directory"' in signature_base_value.parameters
    assert "expires=1750106129" in signature_base_value.parameters


def test_the_signature_covers_the_directory_content():
    key = serialization.load_pem_private_key(PEM.encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)

    body, headers = signed_directory([key], 1750105829, "AAAA")
    expected_digest = f"sha-256=:{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}:"

    assert headers["Content-Digest"] == expected_digest
    assert verify_at("us.posthog.com", headers, key) is True
    assert verify_at("us.posthog.com", {**headers, "Content-Digest": "sha-256=:AAAA:"}, key) is False


def test_the_directory_supports_overlapping_keys_during_rotation():
    keys = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]

    body, headers = signed_directory(keys, 1750105829, "AAAA")

    assert json.loads(body)["keys"] == [public_jwk(key) for key in keys]
    assert verify_at("us.posthog.com", headers, keys[0], "sig1") is True
    assert verify_at("us.posthog.com", headers, keys[1], "sig2") is True


@override_settings(WEB_BOT_AUTH_PRIVATE_KEYS=[PEM], CLOUD_DEPLOYMENT="US")
def test_the_route_serves_a_signed_directory():
    response = Client().get("/.well-known/http-message-signatures-directory")

    assert response.status_code == 200
    assert response["Content-Type"] == CONTENT_TYPE
    assert response["Cache-Control"] == "public, max-age=60"
    assert response["Content-Digest"].startswith("sha-256=:")
    assert response["Signature-Input"].startswith('sig1=("@authority";req "content-digest")')
    assert response["Signature"].startswith("sig1=:")


@override_settings(WEB_BOT_AUTH_PRIVATE_KEYS=[PEM], ALLOWED_HOSTS=["*"], CLOUD_DEPLOYMENT="US")
def test_the_route_ignores_the_host_it_was_asked_on():
    # Reading the authority off the request looks harmless and is the change to guard against. A
    # signer that trusted the Host would hand any site proxying here a directory that verifies there.
    key = serialization.load_pem_private_key(PEM.encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)

    response = Client().get("/.well-known/http-message-signatures-directory", HTTP_HOST="evil.example")

    headers = {
        "Content-Digest": response["Content-Digest"],
        "Signature-Input": response["Signature-Input"],
        "Signature": response["Signature"],
    }
    assert verify_at("us.posthog.com", headers, key) is True
    assert verify_at("evil.example", headers, key) is False


@override_settings(WEB_BOT_AUTH_PRIVATE_KEYS=[], CLOUD_DEPLOYMENT="US")
def test_the_route_is_absent_where_no_key_is_configured():
    # Self-hosted holds no key. A 500 there would read as a broken deployment.
    assert Client().get("/.well-known/http-message-signatures-directory").status_code == 404


@pytest.mark.parametrize(
    "configured_keys,expected_error_message",
    [
        pytest.param([], "is present but contains no keys", id="empty"),
        pytest.param(["not a PEM"], "entry 1 could not be loaded (ValueError)", id="malformed-pem"),
        pytest.param([NON_ED25519_PEM], "entry 1 is not an Ed25519 private key", id="non-ed25519-key"),
        pytest.param(
            [PEM, "not a PEM"],
            "entry 2 could not be loaded (ValueError)",
            id="mixed-valid-and-invalid-keys",
        ),
    ],
)
def test_invalid_key_configuration_is_rejected(configured_keys: list[str], expected_error_message: str) -> None:
    configuration = load_web_bot_auth_private_key_configuration(
        tuple(configured_keys),
        require_at_least_one=True,
    )

    assert configuration.private_keys == ()
    assert configuration.validation_error is not None
    assert expected_error_message in str(configuration.validation_error)


@override_settings(CLOUD_DEPLOYMENT="US")
def test_flattened_private_key_configuration_is_supported() -> None:
    with override_settings(WEB_BOT_AUTH_PRIVATE_KEYS=[PEM.replace("\n", "\\n")]):
        response = Client().get("/.well-known/http-message-signatures-directory")

    assert response.status_code == 200


@pytest.mark.parametrize("configured_keys", [[], ["not a PEM"]], ids=["empty", "malformed-pem"])
@override_settings(WEB_BOT_AUTH_PRIVATE_KEYS_ENV_VAR_PRESENT=True, CLOUD_DEPLOYMENT="US")
def test_the_route_is_unavailable_when_key_configuration_is_invalid(configured_keys: list[str]) -> None:
    with override_settings(WEB_BOT_AUTH_PRIVATE_KEYS=configured_keys):
        assert Client().get("/.well-known/http-message-signatures-directory").status_code == 503


def test_startup_validation_reports_invalid_configuration() -> None:
    code_variable_capture_settings: list[bool | None] = []

    def record_capture_exception_context(*args: object, **kwargs: object) -> None:
        code_variable_capture_settings.append(get_capture_exception_code_variables_context())

    with (
        patch(
            "posthog.exceptions_capture.capture_exception",
            side_effect=record_capture_exception_context,
        ) as capture_exception,
        patch("posthog.utils.safe_cache_add", return_value=True),
    ):
        validation_thread = validate_web_bot_auth_private_keys_in_background(("not a PEM",))
        validation_thread.join(timeout=2)

    assert validation_thread.daemon is True
    assert validation_thread.is_alive() is False
    capture_exception.assert_called_once()
    captured_error = capture_exception.call_args.args[0]
    assert isinstance(captured_error, WebBotAuthPrivateKeyConfigurationError)
    assert captured_error.__traceback__ is None
    assert code_variable_capture_settings == [False]
    assert capture_exception.call_args.kwargs["additional_properties"] == {
        "component": "web_bot_auth_key_directory",
        "configured_key_count": 1,
        "setting": "WEB_BOT_AUTH_PRIVATE_KEYS",
    }


def test_startup_validation_reports_unexpected_loader_errors() -> None:
    with (
        patch(
            "posthog.web_bot_auth_keys.load_web_bot_auth_private_key_configuration",
            side_effect=RuntimeError("loader failed"),
        ),
        patch("posthog.exceptions_capture.capture_exception") as capture_exception,
        patch("posthog.utils.safe_cache_add", return_value=True),
    ):
        validation_thread = validate_web_bot_auth_private_keys_in_background((PEM,))
        validation_thread.join(timeout=2)

    capture_exception.assert_called_once()
    captured_error = capture_exception.call_args.args[0]
    assert isinstance(captured_error, WebBotAuthPrivateKeyConfigurationError)
    assert str(captured_error) == "WEB_BOT_AUTH_PRIVATE_KEYS could not be validated (RuntimeError)"


@pytest.mark.parametrize("region", ["EU", "DEV", None])
@override_settings(WEB_BOT_AUTH_PRIVATE_KEYS=[PEM])
def test_the_route_is_absent_outside_the_us(region: str | None):
    with override_settings(CLOUD_DEPLOYMENT=region):
        assert Client().get("/.well-known/http-message-signatures-directory").status_code == 404
