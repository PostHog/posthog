import json

from posthog.cdp.filters import hog_function_filters_to_expr
from posthog.cdp.validation import transpile_template_code
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.models.plugin import transpile
from posthog.models.team.team import Team


def get_transpiled_function(id: str, source: str, filters: dict, inputs: dict, team: Team) -> str:
    # Wrap in IIFE = Immediately Invoked Function Expression = to avoid polluting global scope
    response = "(function() {\n\n"

    # PostHog-JS adds itself to the window object for us to use
    response += f"const posthog = window['__$$ph_site_app_{id}'] || window['posthog'];\n"

    # Build the inputs in three parts:
    # 1) a simple object with constants/scalars
    inputs_object: list[str] = []
    # 2) a function with a switch + try/catch that calculates the input from globals
    inputs_switch = ""
    # 3) code that adds all calculated inputs to the inputs object
    inputs_append: list[str] = []

    compiler = JavaScriptCompiler()

    # TODO: reorder inputs to make dependencies work
    for key, input in inputs.items():
        value = input.get("value")
        key_string = json.dumps(str(key) or "<empty>")
        if (isinstance(value, str) and "{" in value) or isinstance(value, dict) or isinstance(value, list):
            base_code = transpile_template_code(value, compiler)
            inputs_switch += f"case {key_string}: return {base_code};\n"
            inputs_append.append(f"inputs[{key_string}] = getInputsKey({json.dumps(key)});")
        else:
            inputs_object.append(f"{key_string}: {json.dumps(value)}")

    # Convert the filters to code
    filters_expr = hog_function_filters_to_expr(filters, team, None)
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
        response += "function getInputsKey(key, initial) { try { switch (key) {\n"
        response += inputs_switch
        response += "default: return null; }\n"
        response += "} catch (e) { if(!initial) {console.error('[POSTHOG-JS] Unable to compute value for inputs', key, e);} return null } }\n"
        response += "\n".join(inputs_append) + "\n"
    response += "return inputs;}\n"

    # See plugin-transpiler/src/presets.ts
    # transpile(source, 'site') == `(function () {let exports={};${code};return exports;})`
    response += f"const response = {transpile(source, 'site')}();"
    response += "if ('onLoad' in response) { response.onLoad({ inputs: buildInputs({}, true), posthog: posthog }); }"

    # TODO: also capture events fired between onLoad and onEvent
    response += "if ('onEvent' in response) {"
    response += "posthog.on('eventCaptured', (event) => { "

    # Generate globals for inputs
    response += "const distinct_id = posthog.get_property('distinct_id');"

    # /decide sets "_elementsChainAsString", which gives us either $elements_chain or $elements
    # TODO: We currently only support $elements_chain.
    # TODO: Add the following:
    # - elements_chain: elementsChain,
    # - elements_chain_href: '',
    # - elements_chain_texts: [] as string[],
    # - elements_chain_ids: [] as string[],
    # - elements_chain_elements: [] as string[],
    response += "const elements_chain = event.elements_chain ?? event.properties['$elements_chain'] ?? '';"
    response += "const person = { properties: posthog.get_property('$stored_person_properties') }; "
    response += "const groups = { }; const groupIds = posthog.get_property('$groups') || []; const groupProps = posthog.get_property('$stored_group_properties') || { };"
    response += "for (const [type, properties] of Object.entries(groupProps)) { groups[type] = { id: groupIds[type], type, properties } }"
    response += "const globals = { event: { ...event, elements_chain, distinct_id }, person, groups }; console.log('Globals for inputs', globals);"
    response += "if (globals.event.$set_once) { globals.event.properties.$set_once = globals.event.$set_once; delete globals.event.$set_once; };"
    response += (
        "if (globals.event.$set) { globals.event.properties.$set = globals.event.$set; delete globals.event.$set; };"
    )
    response += "const inputs = buildInputs(globals);"

    # Generate globals for HogQL filters
    # TODO: "group_0" style fields... --> get "index" into posthog-js
    response += "const filterGlobals = { ...groups, ...event, elements_chain, distinct_id, person, inputs, pdi: { distinct_id, person } };"
    response += "let __getGlobal = (key) => __globals[key];\n"
    response += f"const filterMatches = {filters_code};"
    response += "if (filterMatches) { response.onEvent({ event, person, inputs, posthog }); } "
    response += "})}"
    response += "\n\n})();"

    return response
