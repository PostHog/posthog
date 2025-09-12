import json

from posthog.hogql.compiler.javascript import JavaScriptCompiler

from posthog.cdp.filters import hog_function_filters_to_expr
from posthog.cdp.validation import transpile_template_code
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import transpile


def get_transpiled_function(hog_function: HogFunction) -> str:
    response = ""

    # Build the inputs in three parts:
    # 1) a simple object with constants/scalars
    inputs_object: list[str] = []
    # 2) a function with a switch + try/catch that calculates the input from globals
    inputs_switch = ""
    # 3) code that adds all calculated inputs to the inputs object
    inputs_append: list[str] = []

    compiler = JavaScriptCompiler()

    all_inputs = hog_function.inputs or {}
    all_inputs = sorted(all_inputs.items(), key=lambda x: x[1].get("order", -1))
    for key, input in all_inputs:
        value = input.get("value")
        key_string = json.dumps(str(key) or "<empty>")
        if (isinstance(value, str) and "{" in value) or isinstance(value, dict) or isinstance(value, list):
            base_code = transpile_template_code(value, compiler)
            inputs_switch += f"case {key_string}: return {base_code};\n"
            inputs_append.append(f"inputs[{key_string}] = getInputsKey({json.dumps(key)});")
        else:
            inputs_object.append(f"{key_string}: {json.dumps(value)}")

    # A function to calculate the inputs from globals. If "initial" is true, no errors are logged.
    response += "function buildInputs(globals, initial) {\n"

    # Add all constant inputs directly
    response += "let inputs = {\n" + (",\n".join(inputs_object)) + "};\n"

    # Transpiled Hog code needs a "__getGlobal" function in scope
    response += "let __getGlobal = (key) => key === 'inputs' ? inputs : globals[key];\n"

    if inputs_switch:
        # We do it this way to be resilient to errors
        response += "function getInputsKey(key, initial) { try { switch (key) {\n"
        response += inputs_switch
        response += "default: return null; }\n"
        response += "} catch (e) { if(!initial) {console.error('[POSTHOG-JS] Unable to compute value for inputs', key, e);} return null } }\n"
        response += "\n".join(inputs_append) + "\n"

    response += "return inputs;}\n"

    response += f"const source = {transpile(hog_function.hog, 'site')}();"

    # Convert the global filters to code
    filters_expr = hog_function_filters_to_expr(hog_function.filters or {}, hog_function.team, {})
    filters_code = compiler.visit(filters_expr)

    # Convert the mappings to code
    mapping_code = ""

    for mapping in hog_function.mappings or []:
        mapping_disabled = mapping.get("disabled", False)
        if mapping_disabled:
            continue

        mapping_inputs = mapping.get("inputs", {})
        mapping_inputs_schema = mapping.get("inputs_schema", [])
        mapping_filters_expr = hog_function_filters_to_expr(mapping.get("filters", {}) or {}, hog_function.team, {})
        mapping_filters_code = compiler.visit(mapping_filters_expr)

        mapping_code += f"if ({mapping_filters_code}) {{"
        mapping_code += "(function (){"  # IIFE so that the code below has different globals than the filters above
        mapping_code += "const newInputs = structuredClone(inputs); const __getGlobal = (key) => key === 'inputs' ? newInputs : globals[key];\n"

        for schema in mapping_inputs_schema:
            if "key" in schema and schema["key"] not in mapping_inputs:
                mapping_inputs[schema["key"]] = {"value": schema.get("default", None)}

        for key, input in mapping_inputs.items():
            value = input.get("value") if input is not None else schema.get("default", None)
            key_string = json.dumps(str(key) or "<empty>")
            if (isinstance(value, str) and "{" in value) or isinstance(value, dict) or isinstance(value, list):
                base_code = transpile_template_code(value, compiler)
                mapping_code += (
                    f"try {{ newInputs[{json.dumps(key)}] = {base_code}; }} catch (e) {{ console.error(e) }}\n"
                )
            else:
                mapping_code += f"newInputs[{json.dumps(key)}] = {json.dumps(value)};\n"
        mapping_code += "source.onEvent({ inputs: newInputs, posthog });"
        mapping_code += "})();"
        mapping_code += "}\n"

    # We are exposing an init function which is what the client will use to actually run this setup code.
    # The return includes any extra methods that the client might need to use - so far just processEvent
    response += (
        """
    let processEvent = undefined;
    if ('onEvent' in source) {
        processEvent = function processEvent(globals, posthog) {
            if (!('onEvent' in source)) { return; };
            const inputs = buildInputs(globals);
            const filterGlobals = { ...globals.groups, ...globals.event, person: globals.person, inputs, pdi: { distinct_id: globals.event.distinct_id, person: globals.person } };
            let __getGlobal = (key) => filterGlobals[key];
            const filterMatches = """
        + filters_code
        + """;
            if (!filterMatches) { return; }
            """
        + (mapping_code or ";")
        + """
        }
    }

    function init(config) {
        const posthog = config.posthog;
        const callback = config.callback;
        if ('onLoad' in source) {
            const globals = {
                person: {
                    properties: posthog.get_property('$stored_person_properties'),
                }
            }
            const r = source.onLoad({ inputs: buildInputs(globals, true), posthog: posthog });
            if (r && typeof r.then === 'function' && typeof r.finally === 'function') { r.catch(() => callback(false)).then(() => callback(true)) } else { callback(true) }
        } else {
            callback(true);
        }

        const response = {}

        if (processEvent) {
            response.processEvent = (globals) => processEvent(globals, posthog)
        }

        return response
    }

    return { init: init };"""
    )

    # Wrap in IIFE = Immediately Invoked (invokable) Function Expression = to avoid polluting global scope
    # Add collected STL functions above the generated code
    response = "(function() {\n" + compiler.get_stl_code() + "\n" + response + "\n})"

    return response
