import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.exceptions import generate_exception_response
from posthog.hogql import ast
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.hogql.parser import parse_string_template
from posthog.logging.timing import timed
from posthog.plugins.site import get_site_config_from_schema, get_transpiled_site_source


@csrf_exempt
@timed("posthog_cloud_site_app_endpoint")
def get_site_app(request: HttpRequest, id: int, token: str, hash: str) -> HttpResponse:
    try:
        source_file = get_transpiled_site_source(id, token) if token else None
        if not source_file:
            raise Exception("No source file found")

        id = source_file.id
        source = source_file.source
        config = get_site_config_from_schema(source_file.config_schema, source_file.config)

        # Wrap in IIFE = Immediately Invoked Function Expression = to avoid polluting global scope
        response = "(function() {\n\n"

        # Build a switch statement within a try/catch loop and a static dict
        config_switch = ""
        config_dict_items: list[str] = []

        compiler = JavaScriptCompiler()
        for key, value in config.items():
            key_string = json.dumps(str(key) or "<empty>")
            if isinstance(value, str) and "{" in value:
                base_code = compiler.visit(ast.ReturnStatement(expr=parse_string_template(value)))
                config_switch += f"case {key_string}: {base_code};\n"
                config_dict_items.append(f"{key_string}: getConfigKey({json.dumps(key)}, initial)")
            else:
                config_dict_items.append(f"{key_string}: {json.dumps(value)}")

        # Start with the STL functions
        response += compiler.get_inlined_stl() + "\n"

        # This will be used by Hog code to access globals
        response += "let __globals = {};\n"
        response += "function __getGlobal(key) { return __globals[key] }\n"

        if config_switch:
            response += (
                f"function getConfigKey(key, initial) {{ try {{ switch (key) {{\n\n///// calculated properties\n"
            )
            response += config_switch
            response += "\ndefault: return null; }\n"
            response += "} catch (e) { if(!initial) {console.warn('[POSTHOG-JS] Unable to get config field', key, e);} return null } }\n"

        response += (
            f"function getConfig(globals, initial) {{ __globals = globals || {'{}'}; return {{\n\n///// config\n"
        )
        response += ",\n".join(config_dict_items)
        response += "\n\n} }\n"

        response += f"{source}().inject({{config:getConfig({'{}'}, true),getConfig:getConfig,posthog:window['__$$ph_site_app_{id}']}});"

        response += "\n\n})();"

        statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "site_app"})
        return HttpResponse(content=response, content_type="application/javascript")
    except Exception as e:
        capture_exception(e, {"data": {"id": id, "token": token}})
        statsd.incr("posthog_cloud_raw_endpoint_failure", tags={"endpoint": "site_app"})
        return generate_exception_response(
            "site_app",
            "Unable to serve site app source code.",
            code="missing_site_app_source",
            type="server_error",
            status_code=status.HTTP_404_NOT_FOUND,
        )
