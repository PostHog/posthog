from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models.element import Element, chain_to_elements, elements_to_string


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
