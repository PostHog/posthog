import re

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Element
from posthog.models.element.element import elements_to_string
from posthog.models.event import Selector
from posthog.models.property.util import build_selector_regex


class TestSelectors(BaseTest):
    def test_selector_splitting(self):
        selector1 = Selector("div > span > a")
        selector2 = Selector("div span > a")
        selector3 = Selector("div span a")
        selector4 = Selector("div > span a")

        self.assertEqual(len(selector1.parts), 3)
        self.assertEqual(len(selector2.parts), 3)
        self.assertEqual(len(selector3.parts), 3)
        self.assertEqual(len(selector4.parts), 3)

    def test_selector_child(self):
        selector1 = Selector("div span")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, False)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_child_direct_descendant(self):
        selector1 = Selector("div > span")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_attribute(self):
        selector1 = Selector('div[data-id="5"] > span')

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(
            selector1.parts[1].data,
            {"tag_name": "div", "attributes__attr__data-id": "5"},
        )
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_id(self):
        selector1 = Selector('[id="5"] > span')

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"attr_id": "5"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_attribute_with_spaces(self):
        selector1 = Selector('  [data-id="foo bar]"]  ')

        self.assertEqual(selector1.parts[0].data, {"attributes__attr__data-id": "foo bar]"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

    def test_selector_with_spaces(self):
        selector1 = Selector("span    ")

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

    def test_class(self):
        selector1 = Selector("div.classone.classtwo > span")

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(
            selector1.parts[1].data,
            {"tag_name": "div", "attr_class__contains": ["classone", "classtwo"]},
        )
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_nth_child(self):
        selector1 = Selector("div > span:nth-child(3)")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "span", "nth_child": "3"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_unique_order(self):
        selector1 = Selector("div > div")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 1)

    def test_asterisk_in_query(self):
        # Sometimes people randomly add * but they don't do very much, so just remove them
        selector1 = Selector("div > *")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)
        self.assertEqual(len(selector1.parts), 1)

    def test_asterisk_in_middle_of_query(self):
        selector1 = Selector("div > * > div")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, False)
        self.assertEqual(selector1.parts[1].unique_order, 1)

    def test_slash_colon(self):
        # Make sure we strip these for full text search to work in the database
        selector1 = Selector("div#root\\:id")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div", "attr_id": "root:id"})


class TestSelectorRegexMatching(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a sibling class the selector does not name can carry any character",
                ".flex",
                [Element(tag_name="div", attr_class=["flex", "w-1/2", "!mt-0", "hover:bg-blue-500/75"])],
                True,
            ),
            (
                "a target class can carry slashes and bangs",
                ".bg-yellow/50",
                [Element(tag_name="div", attr_class=["bg-yellow/50"])],
                True,
            ),
            (
                "a tailwind arbitrary-value target class",
                ".max-w-[1045px]",
                [Element(tag_name="div", attr_class=["max-w-[1045px]"])],
                True,
            ),
            (
                "an attribute value with a pre-escaped quote",
                'div[title="say \\"hi\\""]',
                [Element(tag_name="div", attributes={"attr__title": 'say "hi"'})],
                True,
            ),
            (
                "a single-quoted attribute value containing double quotes",
                "div[title='say \"hi\"']",
                [Element(tag_name="div", attributes={"attr__title": 'say "hi"'})],
                True,
            ),
            (
                "a neighboring attribute value containing a quote",
                'div[title="hi"]',
                [Element(tag_name="div", attributes={"attr__data-x": 'a"b', "attr__title": "hi"})],
                True,
            ),
            (
                "a semicolon inside an attribute value stays inside the element",
                'input[type="text"]',
                [
                    Element(
                        tag_name="input", attributes={"attr__style": "display: flex; gap: 4px", "attr__type": "text"}
                    )
                ],
                True,
            ),
            (
                "attribute value mismatch",
                'div[title="hi"]',
                [Element(tag_name="div", attributes={"attr__title": "bye"})],
                False,
            ),
            (
                "class not on the element",
                ".flex",
                [Element(tag_name="div", attr_class=["lex"])],
                False,
            ),
            (
                "direct child combinator still matches parent and child",
                "a > b",
                [Element(tag_name="b"), Element(tag_name="a")],
                True,
            ),
            (
                "descendant combinator still matches parent and child",
                "a b",
                [Element(tag_name="b"), Element(tag_name="a")],
                True,
            ),
            (
                "direct child combinator does not match the reversed order",
                "a > b",
                [Element(tag_name="a"), Element(tag_name="b")],
                False,
            ),
        ]
    )
    def test_selector_matches_elements_chain(self, _name, selector, elements, expected):
        regex = build_selector_regex(Selector(selector, escape_slashes=False))
        self.assertEqual(bool(re.search(regex, elements_to_string(elements))), expected)


class TestSelectorRegexMonotonicity(SimpleTestCase):
    SELECTORS = [
        ".flex",
        ".class",
        ".bg-yellow/50",
        ".!ml-auto",
        ".max-w-[1045px]",
        "div",
        "a > b",
        "a b",
        'div[title="say \\"hi\\""]',
        "div[title='say \"hi\"']",
        'a[href="/pricing"]',
        '[id="submit"]',
        "button.btn:nth-child(3)",
    ]

    ELEMENT_CHAINS = [
        [Element(tag_name="div", attr_class=["flex", "w-1/2"])],
        [Element(tag_name="div", attr_class=["bg-yellow/50", "!ml-auto"])],
        [Element(tag_name="div", attr_class=["max-w-[1045px]", "shadow-[0_4px_6px_rgba(0,0,0,0.1)]"])],
        [Element(tag_name="div", attr_class=["class"], attributes={"attr__title": 'say "hi"'})],
        [Element(tag_name="input", attributes={"attr__style": "display: flex; gap: 4px", "attr__type": "text"})],
        [Element(tag_name="b"), Element(tag_name="a")],
        [Element(tag_name="b"), Element(tag_name="div"), Element(tag_name="a")],
        [Element(tag_name="a", href="/pricing", attr_class=["px-2", "hover:underline"])],
        [Element(tag_name="button", attr_class=["btn"], nth_child=3), Element(tag_name="form")],
        [Element(tag_name="button", attr_id="submit", attributes={"attr__type": "button"})],
        # an attribute value that itself looks like a class followed by more text,
        # which the old tail could wander into
        [Element(tag_name="span", attributes={"attr__title": "x.class y"})],
    ]

    @staticmethod
    def _pre_fix_build_selector_regex(selector: Selector) -> str:
        # Frozen copy of build_selector_regex from before the tail and
        # quote-escaping fix, kept to prove the fix only widens matching.
        regex = r""
        for tag in selector.parts:
            if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str) and tag.data["tag_name"] != "*":
                regex += re.escape(tag.data["tag_name"])
            if tag.data.get("attr_class__contains"):
                regex += r".*?\." + r"\..*?".join([re.escape(s) for s in sorted(tag.data["attr_class__contains"])])
            if tag.ch_attributes:
                regex += r".*?"
                for key, value in sorted(tag.ch_attributes.items()):
                    regex += rf'{re.escape(key)}="{re.escape(str(value))}".*?'
            regex += r'([-_a-zA-Z0-9\.:"= \[\]\(\),]*?)?($|;|:([^;^\s]*(;|$|\s)))'
            if tag.direct_descendant:
                regex += r".*"
        return r"(^|;)" + regex if regex else r""

    def test_fix_only_widens_matching(self):
        chains = [elements_to_string(elements) for elements in self.ELEMENT_CHAINS]
        newly_matching_pairs = 0
        for selector_string in self.SELECTORS:
            selector = Selector(selector_string, escape_slashes=False)
            old_regex = self._pre_fix_build_selector_regex(selector)
            new_regex = build_selector_regex(selector)
            for chain in chains:
                old_match = bool(re.search(old_regex, chain))
                new_match = bool(re.search(new_regex, chain))
                with self.subTest(selector=selector_string, chain=chain):
                    if old_match:
                        self.assertTrue(new_match)
                if new_match and not old_match:
                    newly_matching_pairs += 1
        # the corpus has to exercise the widening, or the superset check is vacuous
        self.assertGreater(newly_matching_pairs, 0)
