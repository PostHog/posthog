from typing import Any
from unittest.mock import MagicMock
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate
from posthog.cdp.validation import compile_hog
from posthog.test.base import BaseTest
from hogvm.python.execute import execute_bytecode


class BaseHogFunctionTemplateTest(BaseTest):
    template: HogFunctionTemplate
    compiled_hog: Any

    mock_fetch = MagicMock()

    def setUp(self):
        super().setUp()
        self.compiled_hog = compile_hog(self.template.hog)

    def createHogGlobals(self, globals=None) -> dict:
        # Return an object simulating the
        return {}

    def run_function(self, inputs: dict, globals=None):
        # Create the globals object
        globals = self.createHogGlobals(globals)
        globals["inputs"] = inputs

        # Run the function

        return execute_bytecode(
            self.compiled_hog,
            globals,
            functions={
                "fetch": self.mock_fetch,
            },
        )
