import json

from posthog.cdp.filters import hog_function_filters_to_expr
from posthog.cdp.validation import transpile_template_code
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import transpile


def get_transpiled_function(hog_function: HogFunction) -> str:
    # Wrap in IIFE = Immediately Invoked Function Expression = to avoid polluting global scope
    response = "(function() {\n\n"

    # Build the inputs in three parts:
    # 1) a simple object with constants/scalars
    inputs_object: list[str] = []
    # 2) a function with a switch + try/catch that calculates the input from globals
    inputs_switch = ""
    # 3) code that adds all calculated inputs to the inputs object
    inputs_append: list[str] = []

    compiler = JavaScriptCompiler()

    # TODO: reorder inputs to make dependencies work
    for key, input in (hog_function.inputs or {}).items():
        value = input.get("value")
        key_string = json.dumps(str(key) or "<empty>")
        if (isinstance(value, str) and "{" in value) or isinstance(value, dict) or isinstance(value, list):
            base_code = transpile_template_code(value, compiler)
            inputs_switch += f"case {key_string}: return {base_code};\n"
            inputs_append.append(f"inputs[{key_string}] = getInputsKey({json.dumps(key)});")
        else:
            inputs_object.append(f"{key_string}: {json.dumps(value)}")

    # Convert the filters to code
    filters_expr = hog_function_filters_to_expr(hog_function.filters or {}, hog_function.team, {})
    filters_code = compiler.visit(filters_expr)
    # Start with the STL functions
    response += compiler.get_stl_code() + "\n"

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

    # We are exposing an init function which is what the client will use to actually run this setup code.
    # The return includes any extra methods that the client might need to use - so far just processEvent
    response += (
        """
    let processEvent = undefined;
    if ('onEvent' in source) {
        processEvent = function processEvent(globals) {
            if (!('onEvent' in source)) { return; };
            const inputs = buildInputs(globals);
            const filterGlobals = { ...globals.groups, ...globals.event, person: globals.person, inputs, pdi: { distinct_id: globals.event.distinct_id, person: globals.person } };
            let __getGlobal = (key) => filterGlobals[key];
            const filterMatches = """
        + filters_code
        + """;
            if (filterMatches) { source.onEvent({ ...globals, inputs, posthog }); }
        }
    }

    function init(config) {
        const posthog = config.posthog;
        const callback = config.callback;
        if ('onLoad' in source) {
            const r = source.onLoad({ inputs: buildInputs({}, true), posthog: posthog });
            if (r && typeof r.then === 'function' && typeof r.finally === 'function') { r.catch(() => callback(false)).then(() => callback(true)) } else { callback(true) }
        } else {
            callback(true);
        }

        return {
            processEvent: processEvent
        }
    }

    return { init: init };"""
    )

    response += "\n})"

    return response
