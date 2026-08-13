import re
import random
from typing import cast

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.element import ElementSerializer
from posthog.models.element import Element, chain_to_elements, elements_to_string
from posthog.models.element.element import (
    MAX_ELEMENTS_CHAIN_LENGTH,
    build_attributes_filter,
    chain_to_element_dicts,
    iter_attributes,
)


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


SEGMENT = 'div:nth-child="0"nth-of-type="0"'


class TestChainSplitting(SimpleTestCase):
    @parameterized.expand(
        [
            ("value holding only a backslash", r'a:text="\"', [("a", None)]),
            ("backslash before a newline inside a value", 'a:text="x\\\ny"nth-child="1"', [("a", None)]),
            (
                "value ending in a backslash swallows what follows",
                r'a:text="back\";div:nth-child="0"',
                [("a", r"back\";div:nth-child=")],
            ),
        ]
    )
    def test_chain_splitting_is_stable_for_backslash_edge_cases(
        self, _name: str, chain: str, expected: list[tuple[str | None, str | None]]
    ) -> None:
        elements = chain_to_elements(chain)
        assert [(element.tag_name, element.text) for element in elements] == expected
        assert chain_to_element_dicts(chain) == cast(list[dict], ElementSerializer(elements, many=True).data)

    def test_chain_at_the_length_limit_parses_every_element(self) -> None:
        segments = MAX_ELEMENTS_CHAIN_LENGTH // (len(SEGMENT) + 1)
        chain = ";".join([SEGMENT] * segments)
        assert len(chain) <= MAX_ELEMENTS_CHAIN_LENGTH
        assert len(chain_to_elements(chain)) == segments

    @parameterized.expand(
        [
            ("plain pair", 'a="1"', [("a", "1")]),
            ("adjacent pairs", 'a="1"b="2"', [("a", "1"), ("b", "2")]),
            ("equals inside a value", 'href="/x?b=c"a="1"', [("href", "/x?b=c"), ("a", "1")]),
            ("equals inside a key", 'a=b="v"', [("a=b", "v")]),
            ("escaped quote inside a value", r'k="a\"b"n="1"', [("k", r"a\"b"), ("n", "1")]),
            # A value needs at least one character, so the first quote pair does not close here and
            # the value runs on to the next quote.
            ("empty value runs on", 'a=""b="2"', [("a", '"b=')]),
            ("equals with no quote", "a=1b=2", []),
            ("unterminated quote", 'a="1"b="2', [("a", "1")]),
            ("no attributes at all", "", []),
        ]
    )
    def test_attribute_parsing(self, _name: str, source: str, expected: list[tuple[str, str]]) -> None:
        # The parse is a hand-written scan rather than one regex, because a regex restarts at every
        # position when a match fails and re-reads the rest of the run, which costs time quadratic in
        # an attribute run the event sender controls. These cases pin the parse that scan has to keep.
        assert list(iter_attributes(source)) == expected

    def test_attribute_parsing_matches_the_regex_it_replaced(self) -> None:
        # The scan replaced a regex that had parsed every stored chain until now, so any input that
        # parses differently changes how existing events read. A hand-picked set missed a real case
        # once already: a value that ends where the next one begins (`x="v""k="1""`) left the key's
        # leading quote behind, which turned junk into the reserved `nth-child` key and made
        # `int()` raise on a stored event.
        replaced_regex = re.compile(r"(?P<attribute>(?P<key>.*?)\=\"(?P<value>.*?[^\\])\")", re.MULTILINE)
        alphabet = ["a", "b", "=", '"', "\\", ";", " ", "1", "-", "n"]
        generator = random.Random(1234)

        for _ in range(5000):
            source = "".join(generator.choice(alphabet) for _ in range(generator.randint(0, 18)))
            expected = [(m.group("key"), m.group("value")) for m in replaced_regex.finditer(source)]

            assert list(iter_attributes(source)) == expected, source

    def test_oversized_chain_is_truncated_rather_than_parsed_whole(self) -> None:
        segments = MAX_ELEMENTS_CHAIN_LENGTH // (len(SEGMENT) + 1)
        elements = chain_to_elements(";".join([SEGMENT] * segments * 3))

        assert len(elements) < segments * 3
        # a half-parsed element at the cut would show up as a missing tag or attribute
        assert all(el.tag_name == "div" and el.nth_child == 0 and el.nth_of_type == 0 for el in elements)
        # what survives is a function of the limit, not of how much was sent
        assert len(chain_to_elements(";".join([SEGMENT] * segments * 10))) == len(elements)
        assert len(chain_to_element_dicts(";".join([SEGMENT] * segments * 3))) == len(elements)

    def test_oversized_chain_whose_only_separator_is_near_the_start(self) -> None:
        chain = "a;" + "b" * (MAX_ELEMENTS_CHAIN_LENGTH * 3)
        elements = chain_to_elements(chain)

        # cutting at that separator would throw the whole window away
        assert [el.tag_name for el in elements[:1]] == ["a"]
        assert len(elements[-1].tag_name or "") > MAX_ELEMENTS_CHAIN_LENGTH // 2
