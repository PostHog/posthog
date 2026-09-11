import re
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from posthog.models.event.event import SELECTOR_ATTRIBUTE_REGEX, SelectorPart, _selector_attribute
from posthog.test.regex_timeout import assert_regex_completes
from posthog.utils import _RELATIVE_DATE_RE, relative_date_parse_with_delta_mapping


class TestRegexBoundaries(SimpleTestCase):
    def test_relative_date_pattern_compatibility(self):
        original = re.compile(r"\-?(?P<number>[0-9]+)?(?P<kind>[hdwmqysHDWMQY])(?P<position>Start|End)?")
        rng = random.Random(2)
        corpus = ["-1dStart", "1-2dEnd", "hello", "dStart", "1-2-3h", "-123\n", "123d\ud800"]
        corpus += ["".join(rng.choices("123-abc hdStartEnd\n", k=30)) for _ in range(2_000)]
        for source in corpus:
            old, new = original.search(source), _RELATIVE_DATE_RE.search(source)
            expected = (old.groups(), old.span()) if old else None
            actual = (new.groups(), new.span()) if new else None
            assert actual == expected, repr(source)

    def test_selector_attribute_compatibility(self):
        rng = random.Random(1)
        corpus = ['div[key="value"]', '[id="one"]', 'a[x="x"][y="y"]', "div[x=||]", '😀[a="\ud800"]']
        corpus += ["".join(rng.choices("abXYZ[]='\"|\n😀", k=40)) for _ in range(2_000)]
        for tag in corpus:
            match = re.search(SELECTOR_ATTRIBUTE_REGEX, tag)
            assert _selector_attribute(tag) == (match.groups() if match else None), repr(tag)

    def test_relative_date_without_unit(self):
        def check():
            now = datetime(2026, 9, 11, tzinfo=ZoneInfo("UTC"))
            assert relative_date_parse_with_delta_mapping("9" * 100_000, ZoneInfo("UTC"), now=now) == (
                now,
                {},
                None,
            )

        assert_regex_completes(check)

    def test_many_selector_classes(self):
        def check():
            part = SelectorPart("div" + ".a" * 100_000, False, False)
            assert part.data == {"tag_name": "div", "attr_class__contains": ["a"] * 100_000}

        assert_regex_completes(check)

    def test_selector_without_attribute_terminator(self):
        def check():
            tag = "a" * 100_000 + '[key="value'
            assert SelectorPart(tag, False, False).data == {"tag_name": tag}

        assert_regex_completes(check)

    def test_selector_class_splitting_compatibility(self):
        rng = random.Random(0)
        for _ in range(1_000):
            tag = "div." + "".join(rng.choices("abc.[]\n😀", k=30))
            parts = re.split(r"\.(?![^\[]*\])", tag)
            assert SelectorPart(tag, False, False).data == {
                "tag_name": parts[0],
                "attr_class__contains": parts[1:],
            }
