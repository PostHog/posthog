from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.validation import compile_hog, InputsSchemaItemSerializer
from posthog.models.hog_functions.hog_function import TYPES_WITH_TRANSPILED_FILTERS
from posthog.test.base import BaseTest


class TestTemplatesGeneral(BaseTest):
    def setUp(self):
        super().setUp()

    def test_templates_are_valid(self):
        for template in HOG_FUNCTION_TEMPLATES:
            if template.inputs_schema:
                serializer = InputsSchemaItemSerializer(data=template.inputs_schema, many=True)
                assert serializer.is_valid()

            if template.type not in TYPES_WITH_TRANSPILED_FILTERS:
                bytecode = compile_hog(template.code, template.type)
                assert bytecode[0] == "_H"
