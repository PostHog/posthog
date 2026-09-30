/**
 * Template variable syntax shared with the SDK `compile` helpers
 * (posthog-js `packages/ai/src/prompts.ts`, posthog-python `posthog/ai/prompts.py`).
 * A variable is `{{name}}` where name is letters, digits, `_`, `-` or `.` — no
 * whitespace inside the braces. Anything else, including `{{ spaced }}` and
 * unbalanced braces, is literal text. Keep this regex identical to the SDKs so a
 * prompt saved from the playground compiles the same way in production.
 */
const TEMPLATE_VARIABLE_REGEX = /\{\{([\w.-]+)\}\}/g

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

/**
 * Replace each `{{name}}` with its value. A variable with no value (or an empty
 * one) stays in place, matching the SDK `compile` behavior, so a forgotten value
 * is visible in the model's input instead of silently becoming an empty string.
 */
export function substituteVariables(text: string, values: Record<string, string>): string {
    // Function replacer so values containing `$&`-style patterns substitute literally
    return text.replace(TEMPLATE_VARIABLE_REGEX, (match, name: string) => values[name] || match)
}
