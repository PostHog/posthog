// Mirrors the tag grammar in products/ai_observability/backend/prompt_references.py;
// the backend is authoritative, keep the two in sync.
export const PROMPT_REFERENCE_REGEX =
    /@@@prompt:name=([A-Za-z0-9_-]{1,255})\|(?:version=([1-9][0-9]{0,8})|label=([a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?))@@@/g

export interface PromptReferenceTag {
    raw: string
    name: string
    version: number | null
    label: string | null
}

export function extractPromptReferences(text: string): PromptReferenceTag[] {
    const seen = new Set<string>()
    const references: PromptReferenceTag[] = []
    for (const match of text.matchAll(PROMPT_REFERENCE_REGEX)) {
        if (seen.has(match[0])) {
            continue
        }
        seen.add(match[0])
        references.push({
            raw: match[0],
            name: match[1],
            version: match[2] ? parseInt(match[2], 10) : null,
            label: match[3] ?? null,
        })
    }
    return references
}

export function buildPromptReferenceTag(name: string, selector: { version: number } | { label: string }): string {
    const selectorPart = 'version' in selector ? `version=${selector.version}` : `label=${selector.label}`
    return `@@@prompt:name=${name}|${selectorPart}@@@`
}
