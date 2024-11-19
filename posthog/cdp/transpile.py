import json

from posthog.cdp.filters import hog_function_filters_to_expr
from posthog.cdp.validation import transpile_template_code
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.models.plugin import transpile
from posthog.models.team.team import Team


def get_transpiled_function(id: str, source: str, filters: dict, inputs: dict, team: Team) -> str:
    # Transpile the plugin TS into JS
    transpiled = transpile(source, "site")

    # Wrap in IIFE = Immediately Invoked Function Expression = to avoid polluting global scope
    response = "(function() {\n\n"

    response += f"const posthog = window['__$$ph_site_app_{id}'] || window['posthog'];\n"

    # Build a switch statement within a try/catch loop and a static dict
    config_switch = ""
    config_dict_items: list[str] = []

    compiler = JavaScriptCompiler()

    for key, input in inputs.items():
        value = input.get("value")
        key_string = json.dumps(str(key) or "<empty>")
        if (isinstance(value, str) and "{" in value) or isinstance(value, dict) or isinstance(value, list):
            base_code = transpile_template_code(value, compiler)
            config_switch += f"case {key_string}: return {base_code};\n"
            config_dict_items.append(f"{key_string}: getInputsKey({json.dumps(key)}, initial)")
        else:
            config_dict_items.append(f"{key_string}: {json.dumps(value)}")

    filters_expr = hog_function_filters_to_expr(filters, team, None)
    filters_code = compiler.visit(filters_expr)

    # Start with the STL functions
    response += compiler.get_stl_code() + "\n"

    response += "function getInputs(globals, initial) {\n"
    response += "let __getGlobal = (key) => globals[key];\n"
    # response += f"__globals = globals || {'{}'};\n"
    if config_switch:
        response += "function getInputsKey(key, initial) { try { switch (key) {\n\n///// calculated properties\n"
        response += config_switch
        response += "\ndefault: return null; }\n"
        response += "} catch (e) { if(!initial) {console.warn('[POSTHOG-JS] Unable to get config field', key, e);} return null } }\n"
    response += "return {\n\n///// config\n"
    response += ",\n".join(config_dict_items)
    response += "\n\n} }\n"

    response += f"const response = {transpiled}();"

    response += "if ('onLoad' in response) { response.onLoad({ inputs: getInputs({}, true), posthog: posthog }); }"
    response += "if ('onEvent' in response) {"
    response += "posthog.on('eventCaptured', (event) => { "
    response += "const person = { properties: posthog.get_property('$stored_person_properties') }; "
    response += "const inputs = getInputs({ event, person });"

    response += "let __globals = { ...event, person };"
    response += "let __getGlobal = (key) => __globals[key];\n"
    response += f"const filterMatches = {filters_code};"

    response += "if (filterMatches) { response.onEvent({ event, person, inputs, posthog }); } "
    response += "} ) }"

    response += "\n\n})();"

    return response
