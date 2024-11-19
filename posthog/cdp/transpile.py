import json

from posthog.cdp.validation import transpile_template_code
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.models.plugin import transpile


def get_transpiled_function(id: str, source: str, filters: dict, inputs: dict) -> str:
    # Transpile the plugin TS into JS
    transpiled = transpile(source, "site")

    # Wrap in IIFE = Immediately Invoked Function Expression = to avoid polluting global scope
    response = "(function() {\n\n"

    response += "const posthog = window['__$$ph_site_app_{id}'] || window['posthog'];\n"

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
            config_dict_items.append(f"{key_string}: getConfigKey({json.dumps(key)}, initial)")
        else:
            config_dict_items.append(f"{key_string}: {json.dumps(value)}")

    # TODO: use the filters as well

    # Start with the STL functions
    response += compiler.get_stl_code() + "\n"

    # This will be used by Hog code to access globals
    response += "let __globals = {};\n"
    response += "function __getGlobal(key) { return __globals[key] }\n"

    if config_switch:
        response += f"function getConfigKey(key, initial) {{ try {{ switch (key) {{\n\n///// calculated properties\n"
        response += config_switch
        response += "\ndefault: return null; }\n"
        response += "} catch (e) { if(!initial) {console.warn('[POSTHOG-JS] Unable to get config field', key, e);} return null } }\n"

    response += f"function getConfig(globals, initial) {{ __globals = globals || {'{}'}; return {{\n\n///// config\n"
    response += ",\n".join(config_dict_items)
    response += "\n\n} }\n"

    response += f"const response = {transpiled}();"

    response += f"if ('inject' in response) {{ response.inject({{config:getConfig({'{}'}, true),getConfig:getConfig,posthog:posthog}}); }}"
    response += f"if ('onLoad' in response) {{ response.onLoad({{inputs:getConfig({'{}'}, true),posthog: posthog}}); }}"
    response += f"if ('onEvent' in response) {{ posthog.on('eventCaptured', (event) => {{ "
    response += f"const person = {{ properties: posthog.get_property('$stored_person_properties') }}; "
    response += f"response.onEvent({{ event, person, inputs: getConfig({{ event, person }}), posthog: posthog }}); "
    response += f"}} ) }}"

    response += "\n\n})();"

    return response
