import re
import random
from typing import cast

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.element import ElementSerializer
from posthog.models.element import Element, chain_to_elements, elements_to_string
from posthog.models.element.element import (
    build_attributes_filter,
    chain_to_element_dicts,
    parse_attributes_regex,
    split_chain_regex,
    split_class_attributes,
)
from posthog.test.regex_timeout import assert_regex_completes


class TestElementParsingBoundaries(SimpleTestCase):
    def test_lone_surrogates_are_preserved(self) -> None:
        chain = 'a\ud800.class\udfff:text="value\ud800"attr_\udfff="value\udfff"'
        parsed = chain_to_element_dicts(chain)
        self.assertEqual(parsed[0]["tag_name"], "a\ud800")
        self.assertEqual(parsed[0]["attr_class"], ["class\udfff"])
        self.assertEqual(parsed[0]["text"], "value\ud800")
        self.assertEqual(parsed[0]["attributes"], {"attr_\udfff": "value\udfff"})
        self.assertEqual(parsed, ElementSerializer(chain_to_elements(chain), many=True).data)

    def test_parser_matches_python_regex_grammar(self) -> None:
        legacy_chain = re.compile(r'(?:[^\s;"]|"(?:\\.|[^"])*")+')
        legacy_classes = re.compile(r"(.*?)($|:([a-zA-Z\-\_0-9]*=.*))")
        legacy_attributes = re.compile(r'(?P<attribute>(?P<key>.*?)="(?P<value>.*?[^\\])")', re.MULTILINE)
        rng = random.Random(42)
        corpus = [
            "".join(rng.choices('abAB09_:;.= "\\\n\r\t\x1c\x85\u00a0\u2003\u2028😀', k=rng.randrange(80)))
            for _ in range(1000)
        ]
        corpus.extend(['a:text="hello\\";world";b', 'a:x=""y="value"', 'a:x="one\ntwo"'])
        whitespace = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
        corpus.extend(f'a{character}b:text="x{character}y"' for character in whitespace)
        for chain in corpus:
            self.assertEqual(split_chain_regex.findall(chain), legacy_chain.findall(chain), repr(chain))
            self.assertEqual(parse_attributes_regex.findall(chain), legacy_attributes.findall(chain), repr(chain))
            for element in legacy_chain.findall(chain):
                self.assertEqual(
                    split_class_attributes.findall(element), legacy_classes.findall(element), repr(element)
                )
            self.assertEqual(chain_to_element_dicts(chain), ElementSerializer(chain_to_elements(chain), many=True).data)

    @parameterized.expand(
        [
            ("quotes", 'a:x="' + "\\" * 100_000, None),
            ("attributes", "a:" + "x" * 100_000, None),
            ("classes", "a:" * 50_000, None),
            ("text", 'a:text="' + "x" * 100_000 + '"', "x" * 100_000),
        ]
    )
    def test_long_chain_finishes_without_truncation(self, _name: str, chain: str, expected_text: str | None) -> None:
        def parse() -> None:
            parsed = chain_to_element_dicts(chain)
            self.assertEqual(parsed, ElementSerializer(chain_to_elements(chain), many=True).data)
            self.assertEqual(parsed[0]["text"], expected_text)

        assert_regex_completes(parse)


class TestElement(ClickhouseTestMixin, BaseTest):
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
