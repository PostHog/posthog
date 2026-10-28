from typing import cast

from posthog.test.base import ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.element import ElementSerializer
from posthog.models.element import Element, chain_to_elements, elements_to_string
from posthog.models.element.element import (
    ElementAttribute,
    build_attributes_filter,
    chain_to_element_dicts,
    iter_element_attributes,
)


class TestElement(ClickhouseTestMixin, SimpleTestCase):
    def test_elements_to_string(self) -> None:
        self.maxDiff = None
        elements_string = elements_to_string(
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text="bla bla",
                    attributes={
                        "prop": "value",
                        "number": 33,
                        "data-attr": 'something " that; could mess up',
                        "style": "min-height: 100vh;",
                    },
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(
                    tag_name="button",
                    attr_class=["btn", "btn-primary"],
                    nth_child=0,
                    nth_of_type=0,
                ),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested"),
            ]
        )

        self.assertEqual(
            elements_string,
            ";".join(
                [
                    r'a.small:data-attr="something \" that; could mess up"href="/a-url"nth-child="1"nth-of-type="0"number="33"prop="value"style="min-height: 100vh;"text="bla bla"',
                    'button.btn.btn-primary:nth-child="0"nth-of-type="0"',
                    'div:nth-child="0"nth-of-type="0"',
                    'div:attr_id="nested"nth-child="0"nth-of-type="0"',
                ]
            ),
        )

        elements = chain_to_elements(elements_string)
        self.assertEqual(elements[0].tag_name, "a")
        self.assertEqual(elements[0].href, "/a-url")
        self.assertEqual(elements[0].attr_class, ["small"])
        self.assertDictEqual(
            elements[0].attributes,
            {
                "prop": "value",
                "number": "33",
                "data-attr": r"something \" that; could mess up",
                "style": "min-height: 100vh;",
            },
        )
        self.assertEqual(elements[0].nth_child, 1)
        self.assertEqual(elements[0].nth_of_type, 0)

        self.assertEqual(elements[1].attr_class, ["btn", "btn-primary"])
        self.assertEqual(elements[3].attr_id, "nested")

    @parameterized.expand(
        [
            (
                "escaped quotes and semicolons in attributes",
                r'a.small:data-attr="something \" that; could mess up"href="/a-url"nth-child="1"nth-of-type="0"text="bla bla";button.btn.btn-primary:nth-child="0"nth-of-type="0"',
            ),
            (
                "attr__ prefixed production-shaped chain",
                'svg.LemonIcon.text-3xl:attr__class="LemonIcon text-3xl"attr__fill="currentColor"attr__width="100%"nth-child="1"nth-of-type="1";div:attr_id="nested"nth-child="0"nth-of-type="0"',
            ),
            ("broken class names", "a........small"),
            ("empty chain", ""),
        ]
    )
    def test_chain_to_element_dicts_matches_serialized_models(self, _name: str, chain: str) -> None:
        via_models = cast(list[dict], ElementSerializer(chain_to_elements(chain), many=True).data)
        assert chain_to_element_dicts(chain) == via_models

    @parameterized.expand(
        [
            ("exact name", ["data-attr"], {"attr__data-attr": "x"}),
            ("wildcard", ["data-*"], {"attr__data-attr": "x", "attr__data-tracking-id": "y"}),
            ("no match keeps other fields", ["data-nope"], {}),
            ("multiple wildcards, matching the toolbar's semantics", ["data-*ing-*"], {"attr__data-tracking-id": "y"}),
            (
                "wildcard and exact entries together",
                ["data-*-id", "data-attr"],
                {"attr__data-attr": "x", "attr__data-tracking-id": "y"},
            ),
            (
                "lone wildcard matches every attribute, like the toolbar's regex",
                ["*"],
                {
                    "attr__class": "small",
                    "attr__data-attr": "x",
                    "attr__data-tracking-id": "y",
                    "attr__style": "color: red",
                },
            ),
        ]
    )
    def test_chain_to_element_dicts_filters_attributes(
        self, _name: str, wanted: list[str], expected_attributes: dict
    ) -> None:
        chain = 'a.small:attr__class="small"attr__data-attr="x"attr__data-tracking-id="y"attr__style="color: red"href="/a-url"nth-child="1"nth-of-type="1"'
        element_dicts = chain_to_element_dicts(chain, build_attributes_filter(wanted))
        assert element_dicts[0]["attributes"] == expected_attributes
        assert element_dicts[0]["href"] == "/a-url"
        assert element_dicts[0]["attr_class"] == ["small"]

    def test_chain_to_element_dicts_skips_empty_attribute_keys(self) -> None:
        element_dicts = chain_to_element_dicts('a:="x"nth-child="0"')
        assert element_dicts[0]["attributes"] == {}
        assert element_dicts[0]["nth_child"] == 0

    @parameterized.expand(
        [
            ("long backslash run", 'a:text="' + "\\" * 5000, ["a", "\\" * 5000]),
            ("quote at the end of the chain", 'button:nth-child="1"text="unclosed', ["button", "unclosed"]),
            ("long run of escaped quotes", '"\\' * 100_000, ["\\"] * 100_000),
            ("escaped quote with no value before it", 'a\\"', ["a\\"]),
        ]
    )
    def test_chain_to_element_dicts_ends_element_at_unterminated_quote(
        self, _name: str, chain: str, expected_tag_names: list[str]
    ) -> None:
        element_dicts = chain_to_element_dicts(chain)
        assert [element["tag_name"] for element in element_dicts] == expected_tag_names
        assert all(element["text"] is None for element in element_dicts)

    @parameterized.expand(
        [
            ("href", 'button:nth-child="2";a:href="C:\\"', ["button", "a"], {"href": None, "nth_child": None}),
            ("text", 'a:nth-child="1"text="ends with \\"', ["a"], {"text": None, "nth_child": 1}),
        ]
    )
    def test_chain_to_element_dicts_drops_a_value_that_ends_in_a_backslash_at_the_end_of_the_chain(
        self, _name: str, chain: str, expected_tag_names: list[str], expected_last: dict
    ) -> None:
        element_dicts = chain_to_element_dicts(chain)
        assert [element["tag_name"] for element in element_dicts] == expected_tag_names
        assert {field: element_dicts[-1][field] for field in expected_last} == expected_last

    def test_chain_to_element_dicts_finds_the_tag_past_a_newline_in_a_value(self) -> None:
        element_dicts = chain_to_element_dicts('text="' + "a" * 200_000 + '\nb:href="/a"')
        assert [element["tag_name"] for element in element_dicts] == ["b"]

    @parameterized.expand(
        [
            ("value never closes", 'href="/a"text="' + '\\"' * 2000, [ElementAttribute(key="href", value="/a")]),
            (
                "empty value",
                'alt=""href="/a"',
                [ElementAttribute(key="alt", value=""), ElementAttribute(key="href", value="/a")],
            ),
            (
                "escaped quote inside value",
                'text="say \\"hi\\""',
                [ElementAttribute(key="text", value='say \\"hi\\"')],
            ),
        ]
    )
    def test_iter_element_attributes(self, _name: str, attrs: str, expected: list[ElementAttribute]) -> None:
        assert list(iter_element_attributes(attrs)) == expected

    @parameterized.expand(
        [
            ("empty nth-child", 'a:nth-child=""nth-of-type="2"', {"nth_child": None, "nth_of_type": 2}),
            ("non-numeric nth-of-type", 'a:nth-child="1"nth-of-type="x"', {"nth_child": 1, "nth_of_type": None}),
            (
                "empty value before other attributes",
                'a:attr__title=""href="/a-url"nth-child="1"',
                {"href": "/a-url", "nth_child": 1, "attributes": {"attr__title": ""}},
            ),
        ]
    )
    def test_chain_to_element_dicts_tolerates_malformed_values(self, _name: str, chain: str, expected: dict) -> None:
        element = chain_to_element_dicts(chain)[0]
        assert {field: element[field] for field in expected} == expected

    def test_build_attributes_filter_caps_entry_count(self) -> None:
        many_attrs = [f"data-attr-{i}" for i in range(100)]
        matcher = build_attributes_filter(many_attrs)
        assert matcher is not None
        assert matcher("attr__data-attr-0")
        assert not matcher("attr__data-attr-99")

    def test_build_attributes_filter_normalizes_entries_before_capping(self) -> None:
        matcher = build_attributes_filter([" ", ""] * 10 + [f"data-{i}" for i in range(50)])
        assert matcher is not None
        assert matcher("attr__data-49")

    @parameterized.expand([("empty list", []), ("blank entries only", ["  ", ""])])
    def test_build_attributes_filter_returns_none_when_nothing_to_filter(self, _name: str, wanted: list[str]) -> None:
        assert build_attributes_filter(wanted) is None

    def test_broken_class_names(self):
        elements = chain_to_elements("a........small")
        self.assertEqual(elements[0].tag_name, "a")
        self.assertEqual(elements[0].attr_class, ["small"])

        elements_string = elements_to_string(
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=['small"', "xy:z"],
                    attributes={"attr_class": 'xyz small"'},
                )
            ]
        )

        elements = chain_to_elements(elements_string)
        self.assertEqual(elements[0].tag_name, "a")
        self.assertEqual(elements[0].href, "/a-url")
        self.assertEqual(elements[0].attr_class, ["small", "xy:z"])
