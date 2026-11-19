from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import _builtin_parse_cache, _user_parse_cache, clear_parse_caches

from products.cdp.backend.abuse.classifier import HogFunctionContent
from products.cdp.backend.abuse.rules import Rule, has_outbound_call, matched_rules


def content(
    hog: str = "fetch(inputs.url, {'body': event})",
    function_type: str = "destination",
    inputs: dict[str, Any] | None = None,
    mappings: list[Any] | None = None,
    filters: dict[str, Any] | None = None,
    template_id: str | None = None,
    code_modified_from_template: bool | None = None,
    inputs_schema: list[Any] | None = None,
    masking: dict[str, Any] | None = None,
) -> HogFunctionContent:
    return HogFunctionContent(
        type=function_type,
        template_id=template_id,
        code_modified_from_template=code_modified_from_template,
        hog=hog,
        inputs_schema=inputs_schema or [],
        inputs=inputs if inputs is not None else {"url": {"value": "https://hooks.example.com/orders"}},
        filters=filters or {},
        mappings=mappings or [],
        masking=masking,
    )


def liquid(template: str) -> HogFunctionContent:
    return content(inputs={"body": {"value": template, "templating": "liquid"}})


class TestAbuseRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("public_webhook", content(), ()),
            (
                "metadata_ip_in_code",
                content(hog="fetch('http://169.254.169.254/latest/meta-data')"),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "localhost_with_port_in_input",
                content(inputs={"url": {"value": "http://localhost:8000/api"}}),
                (Rule.INTERNAL_HOST,),
            ),
            ("private_ip", content(inputs={"url": {"value": "http://10.1.2.3/hook"}}), (Rule.INTERNAL_HOST,)),
            ("ipv6_loopback", content(hog="fetch('http://[::1]:8080/')"), (Rule.INTERNAL_HOST,)),
            ("cluster_service", content(hog="fetch('http://api.default.svc.cluster.local/')"), (Rule.INTERNAL_HOST,)),
            ("internal_suffix", content(hog="fetch('https://metadata.google.internal/')"), (Rule.INTERNAL_HOST,)),
            (
                "encoded_in_a_redirect_parameter",
                content(
                    inputs={
                        "url": {"value": "https://redirect.example.com/go?to=http%3A%2F%2F169.254.169.254%2Flatest"}
                    }
                ),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "encoded_twice",
                content(
                    inputs={"url": {"value": "https://redirect.example.com/go?to=http%253A%252F%252F127.0.0.1%252F"}}
                ),
                (Rule.INTERNAL_HOST,),
            ),
            ("userinfo_trick", content(hog="fetch('http://169.254.169.254@example.com/')"), (Rule.INTERNAL_HOST,)),
            (
                "nested_input_value",
                content(inputs={"body": {"value": {"callback": ["http://192.168.0.10/x"]}}}),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "request_catcher",
                content(inputs={"url": {"value": "https://webhook.site/0000-abcd"}}),
                (Rule.REQUEST_CATCHER,),
            ),
            ("tunnel_subdomain", content(hog="fetch('https://abc123.ngrok-free.app/x')"), (Rule.REQUEST_CATCHER,)),
            ("oob_domain", content(hog="fetch('http://probe.oast.fun/')"), (Rule.REQUEST_CATCHER,)),
            ("catcher_lookalike", content(inputs={"url": {"value": "https://notwebhook.site/x"}}), ()),
            ("catcher_name_as_subdomain", content(inputs={"url": {"value": "https://webhook.site.example.com/x"}}), ()),
            (
                "catcher_in_a_mapping_input",
                content(mappings=[{"name": "Orders", "inputs": {"url": {"value": "https://httpbin.org/post"}}}]),
                (Rule.REQUEST_CATCHER,),
            ),
            (
                "local_url_in_an_event_filter",
                content(
                    filters={
                        "properties": [{"key": "$current_url", "value": "http://localhost:8000/", "type": "event"}]
                    }
                ),
                (),
            ),
            (
                "local_url_filter_in_a_transformation",
                content(
                    hog="if (startsWith(event.properties.$current_url, 'http://localhost:3000/')) {\n  return null\n}\nreturn event",
                    function_type="transformation",
                    inputs={},
                ),
                (Rule.INTERNAL_HOST_REFERENCE,),
            ),
            (
                "local_url_compared_in_destination_code",
                content(
                    hog="if (event.properties.$current_url == 'http://127.0.0.1:8000/') { return }\nfetch(inputs.url)"
                ),
                (Rule.INTERNAL_HOST_REFERENCE,),
            ),
            (
                "internal_input_of_a_transformation",
                content(function_type="transformation", inputs={"exclude": {"value": "http://localhost:3000"}}),
                (Rule.INTERNAL_HOST_REFERENCE,),
            ),
            (
                "internal_mapping_input_of_a_destination",
                content(mappings=[{"name": "Orders", "inputs": {"url": {"value": "http://10.0.0.8/orders"}}}]),
                (Rule.INTERNAL_HOST,),
            ),
            ("ipv4_shorthand", content(inputs={"url": {"value": "http://127.1/"}}), (Rule.INTERNAL_HOST,)),
            ("ipv4_as_one_number", content(hog="fetch('http://2130706433/')"), (Rule.INTERNAL_HOST,)),
            ("ipv4_in_hex", content(hog="fetch(f'http://0x7f000001/{event.uuid}')"), (Rule.INTERNAL_HOST,)),
            (
                "ipv4_in_octal_parts",
                content(inputs={"url": {"value": "http://0251.0376.0251.0376/"}}),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "padded_userinfo",
                content(inputs={"url": {"value": "http://" + "a" * 600 + "@127.0.0.1/"}}),
                (Rule.INTERNAL_HOST,),
            ),
            ("ideographic_full_stop", content(inputs={"url": {"value": "http://127\u30021/"}}), (Rule.INTERNAL_HOST,)),
            (
                "fullwidth_hex",
                content(
                    inputs={"url": {"value": "http://\uff10\uff58\uff17\uff46\uff10\uff10\uff10\uff10\uff10\uff11/"}}
                ),
                (Rule.INTERNAL_HOST,),
            ),
            ("quote_inside_a_fetch_literal", content(hog='fetch("http://127.1/?x=\'")'), (Rule.INTERNAL_HOST,)),
            ("escaped_quote_in_a_fetch_literal", content(hog="fetch('http://127.1/?x=\\'y')"), (Rule.INTERNAL_HOST,)),
            ("long_fetch_literal", content(hog="fetch('http://127.1/" + "a" * 3_000 + "')"), (Rule.INTERNAL_HOST,)),
            (
                "huge_authority",
                content(inputs={"url": {"value": "http://" + "a" * 1_000_000}}),
                (Rule.OVERSIZED_INPUT,),
            ),
            (
                "semicolon_in_userinfo",
                content(inputs={"url": {"value": "http://u;v@169.254.169.254/latest"}}),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "extra_slashes_after_scheme",
                content(inputs={"url": {"value": "http:////127.0.0.1/"}}),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "backslashes_after_scheme",
                content(inputs={"url": {"value": "http:\\\\127.0.0.1\\x"}}),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "markdown_link",
                content(inputs={"body": {"value": "[test](https://webhook.site)"}}),
                (Rule.REQUEST_CATCHER,),
            ),
            ("ipv6_loopback_without_port", content(inputs={"url": {"value": "http://[::1]/"}}), (Rule.INTERNAL_HOST,)),
            ("ipv6_unique_local", content(inputs={"url": {"value": "http://[fd00::1]/hook"}}), (Rule.INTERNAL_HOST,)),
            ("chained_schemes", content(hog="http:/a" * 200_000, inputs={}), ()),
            ("very_long_numeric_host", content(hog="fetch('https://" + "1" * 5_000 + "/')"), ()),
            (
                "zero_padded_ipv4_part",
                content(inputs={"url": {"value": "http://0" + "0" * 20 + "177.0.0.1/"}}),
                (Rule.INTERNAL_HOST,),
            ),
            ("public_ipv4_as_one_number", content(inputs={"url": {"value": "http://134744072/"}}), ()),
            ("numeric_looking_domain", content(inputs={"url": {"value": "https://1.2.3.4.example.com/"}}), ()),
            ("many_urls", content(hog="https://example.com/" * 50_000, inputs={}), ()),
            ("templated_host", content(inputs={"url": {"value": "https://{inputs.host}/hook"}}), ()),
            ("oversized_input", content(inputs={"padding": {"value": "B" * 65_537}}), (Rule.OVERSIZED_INPUT,)),
            ("input_at_the_size_limit", content(inputs={"padding": {"value": "B" * 65_536}}), ()),
            (
                "oversized_mapping_input",
                content(mappings=[{"inputs": {"padding": {"value": {"nested": "B" * 70_000}}}}]),
                (Rule.OVERSIZED_INPUT,),
            ),
            (
                "workflow_function_called_from_a_destination",
                content(hog="postHogAddToStaticCohort({'cohort_id': 4242})"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "workflow_function_called_from_a_transformation",
                content(
                    hog="postHogReplayVisionScan({'session_id': event.properties.$session_id})\nreturn event",
                    function_type="transformation",
                    inputs={},
                ),
                (Rule.INTERNAL_FUNCTION,),
            ),
            ("warehouse_webhook_function", content(hog="produceToWarehouseWebhooks(event)"), (Rule.INTERNAL_FUNCTION,)),
            (
                "internal_function_passed_by_name",
                content(hog="let run := postHogCreateTask\nrun({'title': event.event})"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "internal_function_in_an_inline_query_sample",
                content(hog="let q := (select 1 from events sample {postHogCreateTask({})})"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "local_helper_named_like_an_internal_function",
                content(hog="fun sendEmail(text) {\n  return text\n}\nfetch(inputs.url, {'body': sendEmail('hi')})"),
                (),
            ),
            (
                "internal_function_called_before_a_local_of_that_name",
                content(hog="sendEmail({'to': inputs.to})\nlet sendEmail := 1"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "internal_function_in_the_iterable_of_a_loop_variable_of_that_name",
                content(hog="for (let sendEmail in [sendEmail({'to': inputs.to})]) {\n  print(sendEmail)\n}"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "internal_function_named_as_a_local_in_another_scope",
                content(hog="fun helper() {\n  let postHogCreateTask := 1\n}\npostHogCreateTask({})"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "internal_function_name_bound_by_a_catch",
                content(hog="try {\n  fetch(inputs.url)\n} catch (sendEmail) {\n  print(sendEmail)\n}"),
                (),
            ),
            (
                "internal_function_called_in_a_try_with_a_catch_of_that_name",
                content(hog="try {\n  sendEmail({'to': inputs.to})\n} catch (sendEmail) {\n  print(sendEmail)\n}"),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "internal_function_name_in_a_string",
                content(hog="print('postHogCreateTask runs in workflows')\nfetch(inputs.url)"),
                (),
            ),
            (
                "property_named_like_an_internal_function",
                content(hog="fetch(inputs.url, {'body': event.properties.postHogCreateTask})"),
                (),
            ),
            (
                "support_ticket_mirror_destination",
                content(
                    hog="let ticket := postHogGetTicket({'ticket_id': event.properties.ticket_id})\n"
                    "postHogUpdateTicket({'ticket_id': event.properties.ticket_id, 'updates': {'status': 'pending'}})\n"
                    "fetch(inputs.url, {'body': ticket.body})"
                ),
                (),
            ),
            (
                "internal_function_in_unchanged_template_code",
                content(
                    hog="postHogUpdateAccount({'external_id': inputs.account_id, 'updates': inputs.updates})",
                    template_id="template-posthog-update-account",
                    code_modified_from_template=False,
                ),
                (),
            ),
            (
                "internal_function_in_edited_template_code",
                content(
                    hog="postHogUpdateAccount({'external_id': '1', 'updates': {}})",
                    template_id="template-posthog-update-account",
                    code_modified_from_template=True,
                ),
                (Rule.INTERNAL_FUNCTION,),
            ),
            (
                "posthog_capture",
                content(hog="postHogCapture({'event': 'copied', 'distinct_id': event.distinct_id})"),
                (),
            ),
            (
                "huge_liquid_range_in_a_filter",
                content(inputs={"body": {"value": "{{ (1..400000) | sort | size }}", "templating": "liquid"}}),
                (Rule.HUGE_RANGE,),
            ),
            (
                "huge_liquid_for_loop",
                content(
                    inputs={"body": {"value": "{% for i in ( 0 .. 1000000 ) %}x{% endfor %}", "templating": "liquid"}}
                ),
                (Rule.HUGE_RANGE,),
            ),
            (
                "huge_liquid_range_in_a_mapping_input",
                content(
                    mappings=[
                        {
                            "inputs": {
                                "body": {"value": "{% for i in (-5000..5000) %}x{% endfor %}", "templating": "liquid"}
                            }
                        }
                    ]
                ),
                (Rule.HUGE_RANGE,),
            ),
            (
                "liquid_range_at_the_limit",
                content(inputs={"body": {"value": "{% for i in (1..10000) %}{% endfor %}", "templating": "liquid"}}),
                (),
            ),
            (
                "liquid_range_with_a_variable_end",
                content(
                    inputs={
                        "body": {
                            "value": "{% for i in (1..event.properties.count) %}{% endfor %}",
                            "templating": "liquid",
                        }
                    }
                ),
                (),
            ),
            (
                "liquid_range_with_a_very_long_number",
                content(inputs={"body": {"value": "{{ (1.." + "9" * 5_000 + ") | size }}", "templating": "liquid"}}),
                (Rule.HUGE_RANGE,),
            ),
            *(
                (f"liquid_range_bounds_{name}", liquid(f"{{{{ ({low}..{high}) | size }}}}"), (Rule.HUGE_RANGE,))
                for name, low, high in [
                    ("with_a_sign", "+1", "10001"),
                    ("with_decimals", "1.0", "10001.0"),
                    ("quoted", "'1'", "'10001'"),
                    ("quoted_in_exponent_notation", '"1"', '"1e5"'),
                    ("with_a_trailing_point", "1", "10001."),
                    ("with_a_trailing_point_and_a_space", "1. ", "10001"),
                ]
            ),
            *(
                (f"liquid_range_after_{name}", liquid(template), (Rule.HUGE_RANGE,))
                for name, template in [
                    ("a_quoted_tag_closer", '{{ "}}" | concat: (1..20000) | size }}'),
                    ("an_escaped_quote", '{{ "a\\"b" | concat: (1..20000) | size }}'),
                    ("a_quote_in_an_inline_comment", "{% # ' %}{{ (1..20000) | size }}"),
                    ("a_raw_block_with_a_loose_end_tag", "{% raw %}x{% endraw ignored %}{{ (1..20000) | size }}"),
                    (
                        "a_comment_block_closed_by_a_trimmed_end",
                        "{% comment %}x{% endcomment-%}{{ (1..20000) | size }}",
                    ),
                    (
                        "a_comment_block_with_an_end_tag_in_a_quoted_string",
                        '{% comment %}{{ "{% endcomment %}{{ \'x" }}{% endcomment %}{{ (1..20000) | size }}',
                    ),
                    (
                        "a_raw_block_with_a_trimmed_end_tag_inside",
                        "{% raw %}{%- endraw %}{{ 'x }}{% endraw %}{{ (1..20000) | size }}",
                    ),
                    (
                        "a_comment_block_closed_by_an_end_before_a_curly_quote",
                        "{% comment %}x{% endcomment\u201c %}{{ (1..20000) | size }}",
                    ),
                    (
                        "a_raw_block_closed_by_an_end_before_a_curly_quote",
                        "{% raw %}x{% endraw\u201c %}{{ (1..20000) | size }}",
                    ),
                    ("a_raw_block_closed_after_a_liquid_blank", "{% raw %}x{%\u180eendraw %}{{ (1..20000) | size }}"),
                    (
                        "a_raw_block_whose_first_end_tag_meets_another_tag",
                        "{% raw %}{% endraw\u201c {% assign x %}{{ '{% endraw %}{{ (1..20000) | size }}' }}",
                    ),
                    (
                        "a_line_comment_in_a_liquid_block",
                        "{% liquid\n  # the customer's note\n  assign xs = (1..20000)\n%}",
                    ),
                    (
                        "a_comment_block_in_a_liquid_block",
                        "{% liquid\n  comment\n  note\n  endcomment\n  assign xs = (1..20000)\n%}",
                    ),
                    (
                        "a_raw_block_in_a_liquid_block_closed_by_a_trimmed_end",
                        "{% liquid\n  raw\n  - endraw\n  echo (1..20000) | size\n%}",
                    ),
                    (
                        "a_comment_block_in_a_liquid_block_closed_by_a_trimmed_end",
                        "{% liquid\n  comment\n  -endcomment\n  echo (1..20000) | size\n%}",
                    ),
                    (
                        "a_comment_block_closed_by_a_suffixed_end",
                        "{% liquid\n  comment\n  note\n  endcomment#done\n  assign xs = (1..20000)\n%}",
                    ),
                    ("bounds_past_float_precision", "{{ (-1000000000000000000..-999999999999999872) | size }}"),
                    ("html_encoded_quotes", "{{ (&quot;1&quot;..&quot;20000&quot;) | size }}"),
                    ("encoded_spaces", "{{%20(1%20..%2020000)%20|%20size%20}}"),
                    ("unicode_escapes", "{{ ('1'..'\\u0032\\u0030\\u0030\\u0030\\u0030') | size }}"),
                ]
            ),
            *(
                (f"liquid_range_{name}", liquid(template), ())
                for name, template in [
                    ("in_a_quoted_string", "{{ '(1..20000)' }}"),
                    ("in_an_inline_comment", "{% # {{ (1..20000) | size }} %}"),
                    ("in_a_comment_block", "{% comment %}{{ (1..20000) | size }}{% endcomment %}"),
                    ("in_a_raw_block", "{%- raw -%}{% for i in (1..20000) %}{% endfor %}{% endraw %}"),
                    (
                        "in_a_liquid_block_comment_with_a_carriage_return",
                        "{% liquid\n  # note\rassign xs = (1..20000)\n%}",
                    ),
                    ("in_a_liquid_block_line_comment", "{% liquid\n  # (1..20000)\n  echo event.event\n%}"),
                    (
                        "in_a_comment_block_opened_by_a_trimmed_statement",
                        "{% liquid\n  - comment\n  echo (1..20000) | size\n  endcomment\n  echo 1\n%}",
                    ),
                    (
                        "in_a_comment_block_in_a_liquid_block",
                        "{% liquid\n  comment\n  assign xs = (1..20000)\n  endcomment\n  echo 1\n%}",
                    ),
                    ("in_a_raw_block_with_trimmed_tags", "{%raw-%}{{ (1..20000) | size }}{%endraw%}"),
                    (
                        "in_a_raw_block_after_a_trimmed_end_tag",
                        "{% raw %}{% endraw-%}{{ (1..20000) | size }}{% endraw %}",
                    ),
                    (
                        "in_a_raw_block_after_a_python_only_blank",
                        "{% raw %}{%\x1cendraw %}{{ (1..20000) | size }}{% endraw %}",
                    ),
                    (
                        "in_a_raw_block_after_an_end_tag_that_meets_another_tag",
                        "{% raw %}{% endraw\u201c {% assign x %}{{ (1..20000) | size }}{% endraw %}",
                    ),
                    (
                        "in_a_comment_block_after_an_end_tag_in_a_quoted_string",
                        '{% comment %}{{ "{% endcomment %}" }}{{ (1..20000) | size }}{% endcomment %}',
                    ),
                    (
                        "after_a_comment_block_with_an_end_tag_and_a_space",
                        "{% comment %}x{% endcomment- %}{{ (1..20000) | size }}",
                    ),
                    ("after_an_unclosed_quote", "{{ 'Hi }}{{ (1..20000) | size }}"),
                ]
            ),
            ("liquid_range_with_zero_padded_bounds", liquid("{{ (" + "0" * 19 + ".." + "0" * 18 + "1) | size }}"), ()),
            ("reversed_liquid_range", liquid("{{ (" + "9" * 20 + "..1) | size }}"), ()),
            ("range_in_plain_liquid_text", liquid("Pick a number (1..20000)"), ()),
            ("range_in_a_liquid_comment", liquid("{% # (1..20000) %}{{ event.event }}"), ()),
            (
                "range_in_a_hog_template",
                content(inputs={"body": {"value": "{% for i in (1..20000) %}{% endfor %}", "templating": "hog"}}),
                (),
            ),
            (
                "huge_hog_range",
                content(hog="for (let i in range(1000000)) {\n  print(i)\n}\nfetch(inputs.url)"),
                (Rule.HUGE_RANGE,),
            ),
            ("huge_hog_range_with_a_start", content(hog="let ids := range(-5000, 5001)"), (Rule.HUGE_RANGE,)),
            ("hog_range_at_the_limit", content(hog="let ids := range(10000)"), ()),
            ("local_function_named_range", content(hog="fun range(n) {\n  return [n]\n}\nprint(range(20000))"), ()),
            (
                "huge_range_beside_a_local_named_range_in_another_scope",
                content(hog="fun helper() {\n  let range := 1\n}\nprint(range(20000))"),
                (Rule.HUGE_RANGE,),
            ),
            (
                "local_lambda_named_replace_all",
                content(hog="let replaceAll := (s, a, b) -> s\nprint(replaceAll(event.event, '', 'xx'))"),
                (),
            ),
            (
                "huge_range_in_a_hog_template_input",
                content(inputs={"payload": {"value": "{range(1000000)}", "templating": "hog"}}),
                (Rule.HUGE_RANGE,),
            ),
            (
                "replace_all_in_an_input_with_default_templating",
                content(inputs={"payload": {"value": {"body": "{replaceAll(event.event, '', 'xx')}"}}}),
                (Rule.REPLACE_AMPLIFICATION,),
            ),
            (
                "huge_range_in_a_mapping_hog_template_input",
                content(mappings=[{"inputs": {"ids": {"value": ["{range(-5000, 5001)}"], "templating": "hog"}}}]),
                (Rule.HUGE_RANGE,),
            ),
            (
                "replace_all_in_the_masking_hash",
                content(masking={"hash": "{replaceAll(event.distinct_id, '', 'xx')}", "ttl": 1800}),
                (Rule.REPLACE_AMPLIFICATION,),
            ),
            (
                "range_in_an_input_without_templating",
                content(inputs={"payload": {"value": "{range(1000000)}", "templating": False}}),
                (),
            ),
            (
                "range_in_an_input_the_schema_marks_literal",
                content(
                    inputs={"payload": {"value": "{range(1000000)}"}},
                    inputs_schema=[{"key": "payload", "type": "string", "templating": False}],
                ),
                (),
            ),
            ("hog_range_with_a_float_bound", content(hog="print(range(10001.0))"), (Rule.HUGE_RANGE,)),
            ("hog_range_with_a_string_bound", content(hog="print(range('1', '20000'))"), (Rule.HUGE_RANGE,)),
            (
                "replace_all_with_an_empty_search",
                content(hog="fetch(inputs.url, {'body': replaceAll(event.event, '', 'xxxxxxxx')})"),
                (Rule.REPLACE_AMPLIFICATION,),
            ),
            (
                "replace_all_with_a_computed_replacement",
                content(hog="let body := replaceAll(event.event, '', event.event)"),
                (Rule.REPLACE_AMPLIFICATION,),
            ),
            ("replace_all_removing_a_character", content(hog="let phone := replaceAll(inputs.phone, '-', '')"), ()),
            ("replace_all_of_nothing_with_nothing", content(hog="let name := replaceAll(event.event, '', '')"), ()),
            (
                "several_rules",
                content(
                    hog="fetch('https://webhook.site/x'); fetch('http://127.0.0.1/')",
                    inputs={"padding": {"value": "B" * 100_000}},
                ),
                (Rule.INTERNAL_HOST, Rule.REQUEST_CATCHER, Rule.OVERSIZED_INPUT),
            ),
        ]
    )
    def test_matched_rules(self, _name: str, function: HogFunctionContent, expected: tuple[Rule, ...]) -> None:
        assert matched_rules(function) == expected

    @parameterized.expand(
        [
            ("direct_fetch", content(), True),
            ("no_call", content(hog="event.properties.internal := true\nreturn event", inputs={}), False),
            (
                "fetch_only_in_a_string_and_a_comment",
                content(hog="print('fetch(inputs.url)')\n// fetch(inputs.url)\nreturn event", inputs={}),
                False,
            ),
            (
                "call_to_a_local_function_named_fetch",
                content(hog="fun fetch(url) {\n  return url\n}\nfetch('x')"),
                True,
            ),
            (
                "fetch_beside_a_local_of_that_name_in_another_scope",
                content(hog="fun f() {\n  let fetch := 1\n}\nprint(fetch('x'))"),
                True,
            ),
            ("fetch_referenced_without_a_call", content(hog="let senders := {'a': fetch}\nreturn senders"), True),
            ("fetch_in_a_lambda_callback", content(hog="arrayMap(url -> fetch(url), [inputs.url])"), True),
            (
                "property_rewrite_with_builtins_and_lambda_callbacks",
                content(
                    hog="event.properties.internal := has(inputs.internal_ips, event.properties.$ip)\n"
                    "event.properties.tags := arrayMap(tag -> lower(trim(tag)), event.properties.tags ?? [])\n"
                    "event.properties.internal_tags := arrayFilter(tag -> has(inputs.internal_tags, tag), "
                    "event.properties.tags)\n"
                    "return event",
                    function_type="transformation",
                    inputs={},
                ),
                False,
            ),
            ("closure_from_an_input_called_by_name", content(hog="let send := inputs.sender\nsend(inputs.url)"), True),
            ("closure_called_as_a_member", content(hog="inputs.sender(inputs.url)"), True),
            ("closure_from_an_input_as_a_callback", content(hog="arrayMap(inputs.sender, [inputs.url])"), True),
            (
                "closure_returned_by_a_local_function",
                content(hog="fun identity(x) {\n  return x\n}\nidentity(inputs.sender)(inputs.url)"),
                True,
            ),
            ("closure_returned_by_a_builtin", content(hog="coalesce(inputs.sender)(inputs.url)"), True),
            (
                "closure_swapped_in_through_upvalues",
                content(
                    hog="let evil := inputs.sender\nlet good := x -> x\nlet send := x -> good(x)\n"
                    "let capture := () -> evil\nsend.upvalues[1] := capture.upvalues[1]\nsend(inputs.url)"
                ),
                True,
            ),
            (
                "closure_called_as_a_tag",
                content(hog="let send := inputs.sender\nlet response := <send url={inputs.url} />"),
                True,
            ),
            (
                "closure_called_through_an_implicit_catch_local",
                content(hog="try {\n  throw Error('x')\n} catch {\n  e := inputs.sender\n  e(inputs.url)\n}"),
                True,
            ),
            (
                "closure_called_as_a_tag_through_an_implicit_catch_local",
                content(
                    hog="try {\n  throw Error('x')\n} catch {\n  e := inputs.sender\n  return <e url={inputs.url} />\n}"
                ),
                True,
            ),
            (
                "inline_query",
                content(hog="let q := (select event from events limit 1)"),
                True,
            ),
            (
                "closure_called_through_the_for_in_iterable_temporary",
                content(hog="for (let x in [inputs.sender, <__H_expr_H__ url={inputs.url} />]) {\n  print(x)\n}"),
                True,
            ),
            ("send_email", content(hog="sendEmail({'to': inputs.to})"), True),
            ("posthog_capture", content(hog="postHogCapture({'event': 'copied'})"), True),
            ("ticket_function", content(hog="postHogGetTicket({'ticket_id': event.properties.ticket_id})"), True),
            (
                "fetch_in_a_hog_template_input",
                content(hog="return event", inputs={"url": {"value": "{fetch(event.uuid)}"}}),
                True,
            ),
            (
                "fetch_in_the_masking_hash",
                content(hog="return event", inputs={}, masking={"hash": "{fetch(event.uuid)}"}),
                True,
            ),
            ("code_that_does_not_parse", content(hog="let x := (", inputs={}), True),
            (
                "fetch_in_unchanged_template_code",
                content(template_id="template-webhook", code_modified_from_template=False),
                True,
            ),
            *(
                (
                    f"{prefix}_runs_code_other_than_its_hog",
                    content(hog="return event", inputs={}, template_id=f"{prefix}-x"),
                    True,
                )
                for prefix in ("plugin", "segment", "native")
            ),
        ]
    )
    def test_has_outbound_call(self, _name: str, function: HogFunctionContent, expected: bool) -> None:
        assert has_outbound_call(function) is expected

    def test_parsed_code_and_templates_stay_out_of_the_parse_cache(self) -> None:
        clear_parse_caches()
        function = content(
            hog="let ids := range(10)\nfetch(inputs.url, {'body': ids})",
            inputs={"token": {"value": "{replaceAll('a decrypted secret, long enough to be cached', '', 'x')}"}},
        )

        assert matched_rules(function) == (Rule.REPLACE_AMPLIFICATION,)
        assert _builtin_parse_cache.currsize + _user_parse_cache.currsize == 0
