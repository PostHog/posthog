import dataclasses

from posthog.test.base import BaseTest

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.validation import InputsSchemaItemSerializer, compile_hog
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.hog_function import TYPES_WITH_TRANSPILED_FILTERS


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

    def test_sync_template_to_db(self):
        template_data = dataclasses.asdict(HOG_FUNCTION_TEMPLATES[0])
        template = sync_template_to_db(template_data)
        assert template.template_id == template_data["id"]
        assert template.name == template_data["name"]
        assert template.code == template_data["code"]
        assert template.type == template_data["type"]
        assert template.inputs_schema == template_data["inputs_schema"]
        assert template.category == template_data["category"]
        assert template.description == template_data["description"]
        assert template.filters == template_data["filters"]

    def test_sync_existing_template(self):
        template_data = HOG_FUNCTION_TEMPLATES[0]
        template_id = template_data.id
        template = sync_template_to_db(template_data)
        assert HogFunctionTemplate.objects.filter(template_id=template_id).count() == 1
        assert template.sha == "721860af"

        template_data_dict = dataclasses.asdict(template_data)
        template = sync_template_to_db(template_data_dict)  # Test it as a dictionary
        assert template.sha == "721860af"
        assert HogFunctionTemplate.objects.filter(template_id=template_id).count() == 1

        template_data_dict["code"] = "return 1"
        template = sync_template_to_db(template_data_dict)
        assert template.sha == "a7ba7533"
        assert template.code == "return 1"
        assert HogFunctionTemplate.objects.filter(template_id=template_id).count() == 1
