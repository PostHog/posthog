import json
import functools
from collections.abc import Callable
from typing import Any, Optional, cast

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock

import STPyV8

from posthog.cdp.site_functions import get_transpiled_function
from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, sync_template_to_db
from posthog.cdp.validation import compile_hog
from posthog.models import HogFunction
from posthog.models.utils import uuid7

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.stl import now


# TODO this test class only tests part of the template. The hog code is tested, the default mappings are not
class BaseHogFunctionTemplateTest(BaseTest):
    template: HogFunctionTemplateDC
    compiled_hog: Any
    mock_fetch = MagicMock()
    mock_print = MagicMock()
    mock_posthog_capture = MagicMock()
    fetch_responses: dict[str, dict[Any, Any]] = {}

    def setUp(self):
        super().setUp()
        self.compiled_hog = compile_hog(self.template.code, self.template.type)

        self.mock_print = MagicMock(side_effect=lambda *args: print("[DEBUG HogFunctionPrint]", *args))  # noqa: T201
        # Side effect - log the fetch call and return  with sensible output
        self.mock_fetch = MagicMock(
            side_effect=lambda *args: print("[DEBUG HogFunctionFetch]", *args) or self.mock_fetch_response(*args)  # noqa: T201
        )
        self.mock_posthog_capture = MagicMock(
            side_effect=lambda *args: print("[DEBUG HogFunctionPostHogCapture]", *args)  # noqa: T201
        )

    def mock_fetch_response(self, url, *args):
        return self.fetch_responses.get(url, {"status": 200, "body": {}})

    def get_mock_fetch_calls(self):
        # Return a simple array which is easier to debug
        return [call.args for call in self.mock_fetch.mock_calls]

    def get_mock_print_calls(self):
        # Return a simple array which is easier to debug
        return [call.args for call in self.mock_print.mock_calls]

    def get_mock_posthog_capture_calls(self):
        # Return a simple array which is easier to debug
        return [call.args for call in self.mock_posthog_capture.mock_calls]

    def createHogGlobals(self, globals=None) -> dict:
        # Return an object simulating the
        data = {
            "event": {
                "uuid": "event-id",
                "event": "event-name",
                "name": "event-name",
                "distinct_id": "distinct-id",
                "properties": {"$current_url": "https://example.com"},
                "timestamp": "2024-01-01T00:00:00Z",
                "elements_chain": "",
            },
            "person": {"id": "person-id", "properties": {"email": "example@posthog.com"}},
            "source": {"url": "https://us.posthog.com/hog_functions/1234"},
        }

        if globals:
            if globals.get("event"):
                cast(dict, data["event"]).update(globals["event"])
            if globals.get("person"):
                cast(dict, data["person"]).update(globals["person"])

        return data

    def run_function(self, inputs: dict, globals=None, functions: Optional[dict] = None):
        self.mock_fetch.reset_mock()
        self.mock_print.reset_mock()
        # Create the globals object
        globals = self.createHogGlobals(globals)
        globals["inputs"] = inputs

        # Run the function

        final_functions: dict = {
            "fetch": self.mock_fetch,
            "print": self.mock_print,
            "postHogCapture": self.mock_posthog_capture,
        }

        if functions:
            final_functions.update(functions)

        return execute_bytecode(
            self.compiled_hog,
            globals,
            functions=final_functions,
        )


class BaseSiteDestinationFunctionTest(APIBaseTest):
    template: HogFunctionTemplateDC
    track_fn: str
    inputs: dict

    def setUp(self):
        super().setUp()
        # Create the template in the DB
        sync_template_to_db(self.template)
        self.organization.available_product_features = [{"name": "data_pipelines", "key": "data_pipelines"}]
        self.organization.save()

    @functools.lru_cache
    def _get_transpiled(self, edit_payload: Optional[Callable[[dict], dict]] = None):
        # TODO do this without calling the API. There's a lot of logic in the endpoint which would need to be extracted
        payload = {
            "description": self.template.description,
            "enabled": True,
            "filters": self.template.filters,
            "icon_url": self.template.icon_url,
            "inputs": self.inputs,
            "mappings": [
                {
                    "filters": m.filters,
                    "inputs": {i["key"]: {"value": i["default"]} for i in (m.inputs_schema or [])},
                    "inputs_schema": m.inputs_schema,
                    "name": m.name,
                }
                for m in (self.template.mapping_templates or [])
            ],
            "masking": self.template.masking,
            "name": self.template.name,
            "template_id": self.template.id,
            "type": self.template.type,
        }
        if edit_payload:
            payload = edit_payload(payload)
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data=payload,
        )
        assert response.status_code in (200, 201)
        function_id = response.json()["id"]

        # load from the DB based on the created ID
        hog_function = HogFunction.objects.get(id=function_id)

        return get_transpiled_function(hog_function)

    def _process_event(
        self,
        event_name: str,
        event_properties: Optional[dict] = None,
        person_properties: Optional[dict] = None,
        edit_payload: Optional[Callable[[dict], dict]] = None,
    ):
        event_id = str(uuid7())
        js_globals = {
            "event": {"uuid": event_id, "event": event_name, "properties": event_properties or {}, "timestamp": now()},
            "person": {"properties": person_properties or {}},
            "groups": {},
        }
        # We rely on the fact that most tracking scripts have idempotent init functions.
        # This means that we can add our own tracking function first, and the regular init code (which typically adds an HTML script element) won't run.
        # This lets us run the processEvent code in a minimal JS environment, and capture the outputs for given inputs.
        js = f"""
            {JS_STDLIB}

            const calls = [];
            const {self.track_fn} = (...args) => calls.push(args);
            window.{self.track_fn} = {self.track_fn};

            const globals = {json.dumps(js_globals)};
            const posthog = {{
                get_property: (key) => key === '$stored_person_properties' ? globals.person.properties : null,
                config: {{
                    debug: true,
                }}
            }};

            const initFn = {self._get_transpiled(edit_payload)}().init;

            const processEvent = initFn({{ posthog, callback: console.log }}).processEvent;

            processEvent(globals, posthog);;
            """

        with STPyV8.JSContext() as ctxt:
            ctxt.eval(js)
            calls_json = ctxt.eval(
                "JSON.stringify(calls)"
            )  # send a string type over the bridge as complex types can cause crashes
            calls = json.loads(calls_json)
            assert isinstance(calls, list)
            return event_id, calls


# STPyV8 doesn't provide a window or document object, so set these up with a minimal implementation
JS_STDLIB = """
const document = {};
const window = {};

// easy but hacky impl, if we need a correct one, see
// https://github.com/zloirock/core-js/blob/4b7201bb18a66481d8aa7ca28782c151bc99f152/packages/core-js/modules/web.structured-clone.js#L109
const structuredClone = (obj) => JSON.parse(JSON.stringify(obj));
window.structuredClone = structuredClone;
"""
