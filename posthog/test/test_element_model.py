from typing import cast

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.api.element import ElementSerializer
from posthog.models.element import Element, chain_to_elements, elements_to_string
from posthog.models.element.element import build_attributes_filter, chain_to_element_dicts


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
        # chain_to_element_dicts intentionally drops the redundant attr__class from the
        # attributes map (the class list already lives in the top-level attr_class array),
        # unlike the model-serialization path used for event display; mirror that here
        for element in via_models:
            element["attributes"].pop("attr__class", None)
        assert chain_to_element_dicts(chain) == via_models

    @parameterized.expand(
        [
            ("depth of one keeps only the clicked element", 1, 1),
            ("depth of two keeps the clicked element and one ancestor", 2, 2),
            ("depth larger than the chain keeps every element", 10, 3),
            ("no cap keeps every element", None, 3),
        ]
    )
    def test_chain_to_element_dicts_bounds_chain_depth(
        self, _name: str, max_depth: int | None, expected_count: int
    ) -> None:
        chain = 'button:nth-child="0";div:nth-child="1";body:nth-child="2"'
        element_dicts = chain_to_element_dicts(chain, max_depth=max_depth)
        assert [element["order"] for element in element_dicts] == list(range(expected_count))
        # the clicked element (order 0) is always kept first
        assert element_dicts[0]["tag_name"] == "button"

    def test_chain_to_element_dicts_does_not_duplicate_attr_class(self) -> None:
        chain = 'svg.LemonIcon.text-3xl:attr__class="LemonIcon text-3xl"attr__fill="currentColor"nth-child="1"'
        element = chain_to_element_dicts(chain)[0]
        assert element["attr_class"] == ["LemonIcon", "text-3xl"]
        assert "attr__class" not in element["attributes"]
        assert element["attributes"] == {"attr__fill": "currentColor"}

    def test_chain_to_element_dicts_backfills_attr_class_when_tag_has_no_classes(self) -> None:
        # some chains carry attr__class without the tag's .class tokens; keep the class list
        chain = 'div:attr__class="one two"nth-child="0"'
        element = chain_to_element_dicts(chain)[0]
        assert element["attr_class"] == ["one", "two"]
        assert "attr__class" not in element["attributes"]

    def test_chain_to_element_dicts_keeps_attr_class_when_explicitly_requested(self) -> None:
        chain = 'svg.LemonIcon:attr__class="LemonIcon"nth-child="1"'
        element = chain_to_element_dicts(chain, build_attributes_filter(["class"]))[0]
        assert element["attributes"] == {"attr__class": "LemonIcon"}

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
