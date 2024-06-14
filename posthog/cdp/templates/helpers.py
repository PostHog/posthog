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
    mock_print = MagicMock()

    def setUp(self):
        super().setUp()
        self.compiled_hog = compile_hog(self.template.hog, supported_functions={"fetch", "print", "replace"})

        self.mock_print = MagicMock(side_effect=lambda *args: print("[DEBUG HogFunctionPrint]", *args))  # noqa: T201
        # Side effect - log the fetch call and return  with sensible output
        self.mock_fetch = MagicMock(
            side_effect=lambda *args: print("[DEBUG HogFunctionFetch]", *args) or self.mock_fetch_response(*args)  # noqa: T201
        )

    mock_fetch_response = lambda *args: {"status": 200, "body": {}}

    def get_mock_fetch_calls(self):
        # Return a simple array which is easier to debug
        return [call.args for call in self.mock_fetch.mock_calls]

    def get_mock_print_calls(self):
        # Return a simple array which is easier to debug
        return [call.args for call in self.mock_print.mock_calls]

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
                "print": self.mock_print,
                "replace": lambda a, b, c: a.replace(b, c),
            },
        )
