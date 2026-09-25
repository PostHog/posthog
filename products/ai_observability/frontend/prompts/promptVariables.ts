const PROMPT_VARIABLE_REGEX = /\{\{([^}]+)\}\}/g

export function extractPromptVariables(text: string): string[] {
    return [...new Set(Array.from(text.matchAll(PROMPT_VARIABLE_REGEX), (match) => match[1].trim()))]
}

/** Replace each `{{name}}` that has a non-empty value. Placeholders without a value stay as they are. */
export function fillPromptVariables(text: string, values: Record<string, string>): string {
    return text.replace(PROMPT_VARIABLE_REGEX, (placeholder, name: string) => {
        const value = values[name.trim()]
        return value ? value : placeholder
    })
}
