from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.validation import compile_hog, validate_inputs_schema
from posthog.test.base import BaseTest


class TestTemplatesGeneral(BaseTest):
    def setUp(self):
        super().setUp()

    def test_templates_are_valid(self):
        for template in HOG_FUNCTION_TEMPLATES:
            bytecode = compile_hog(template.hog)
            assert bytecode[0] == "_h"
            assert validate_inputs_schema(template.inputs_schema)
