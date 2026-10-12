/**
 * Template variable syntax shared with the SDK `compile` helpers
 * (posthog-js `packages/ai/src/prompts.ts`, posthog-python `posthog/ai/prompts.py`).
 * A variable is `{{name}}` where name is letters, digits, `_`, `-` or `.` — no
 * whitespace inside the braces. Anything else, including `{{ spaced }}` and
 * unbalanced braces, is literal text. Keep this regex identical to the SDKs so a
 * prompt saved from the playground compiles the same way in production.
 */
const TEMPLATE_VARIABLE_REGEX = /\{\{([\w.-]+)\}\}/g

export interface TemplateSegment {
    text: string
    /** The variable name when this segment is a `{{name}}` token, null for plain text. */
    variableName: string | null
}

/**
 * Split text into plain runs and `{{name}}` tokens, for rendering the same string
 * with the tokens styled. The concatenated segment texts must equal the input
 * exactly: the editor backdrop renders these behind a transparent textarea, and a
 * dropped character pulls the caret away from the glyphs under it.
 */
export function segmentTemplateText(text: string): TemplateSegment[] {
    const segments: TemplateSegment[] = []
    let index = 0
    for (const match of text.matchAll(TEMPLATE_VARIABLE_REGEX)) {
        if (match.index > index) {
            segments.push({ text: text.slice(index, match.index), variableName: null })
        }
        segments.push({ text: match[0], variableName: match[1] })
        index = match.index + match[0].length
    }
    if (index < text.length) {
        segments.push({ text: text.slice(index), variableName: null })
    }
    return segments
}

/** Distinct variable names in order of first appearance. */
export function extractVariables(text: string): string[] {
    const names: string[] = []
    for (const match of text.matchAll(TEMPLATE_VARIABLE_REGEX)) {
        if (!names.includes(match[1])) {
            names.push(match[1])
        }
    }
    return names
}

/** Distinct variable names across several texts, in order of first appearance. */
export function extractVariablesFromTexts(texts: string[]): string[] {
    const names: string[] = []
    for (const text of texts) {
        for (const name of extractVariables(text)) {
            if (!names.includes(name)) {
                names.push(name)
            }
        }
    }
    return names
}

/**
 * Own-property read of a variable value. A plain record inherits `constructor`,
 * `toString` and the rest of Object.prototype, so a bare `values[name]` would
 * hand function source text to a `{{constructor}}` placeholder.
 */
export function getVariableValue(values: Record<string, string>, name: string): string {
    return Object.prototype.hasOwnProperty.call(values, name) ? values[name] : ''
}

/**
 * Replace each `{{name}}` with its value. A variable with no value (or an empty
 * one) stays in place, matching the SDK `compile` behavior, so a forgotten value
 * is visible in the model's input instead of silently becoming an empty string.
 */
export function substituteVariables(text: string, values: Record<string, string>): string {
    // Function replacer so values containing `$&`-style patterns substitute literally
    return text.replace(TEMPLATE_VARIABLE_REGEX, (match, name: string) => getVariableValue(values, name) || match)
}
