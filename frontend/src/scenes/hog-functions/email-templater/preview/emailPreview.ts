import { LiquidRenderer } from 'lib/utils/liquid'

/** The person values a preview renders against, shaped like the worker's `person` global. */
export interface EmailPreviewPerson {
    id: string
    properties: Record<string, any>
}

/**
 * Render one templated email field against a person, the way the send will.
 *
 * Returns the template unchanged when it can't be parsed, because a preview must never be the
 * thing that breaks the review step.
 */
export function renderEmailPreview(
    template: string,
    person: EmailPreviewPerson | null,
    markUnresolved?: (source: string) => string
): string {
    if (!template || !person) {
        return template
    }
    const context = {
        person: {
            id: person.id,
            properties: person.properties,
        },
        // Injected by the email service per recipient. Stand it in so a preview doesn't report the
        // unsubscribe link every marketing email carries as a missing variable.
        unsubscribe_url: '#unsubscribe',
        now: new Date(),
    }
    try {
        return LiquidRenderer.renderKeepingUnresolved(template, context, markUnresolved)
    } catch {
        return template
    }
}

// Private-use characters fence each unresolved tag's label, so the html and the plain-text previews
// can each turn them into a chip after rendering, without the marker ever reading as Liquid.
const CHIP_START = '\uE000'
const CHIP_END = '\uE001'
const CHIP_PATTERN = /\uE000([^\uE001]*)\uE001/g

/** Renders the template against the person, fencing each tag the person has no value for. */
export function renderEmailPreviewMarked(template: string, person: EmailPreviewPerson | null): string {
    return renderEmailPreview(template, person, (source) => `${CHIP_START}${unresolvedLabel(source)}${CHIP_END}`)
}

/** "{{ person.properties.first_name }}" reads as "first name". */
function unresolvedLabel(source: string): string {
    const path = source.replace(/^\{\{-?|-?\}\}$/g, '').trim()
    return (path.split('.').pop() ?? path).replace(/[_$]/g, ' ').trim()
}

export function countUnresolved(...rendered: string[]): number {
    return rendered.reduce((count, text) => count + (text.match(CHIP_PATTERN)?.length ?? 0), 0)
}

/** Splits marked text into plain strings and chip labels, chips at odd indexes. */
export function splitUnresolved(text: string): string[] {
    return text.split(/\uE000|\uE001/)
}

// Inline styles, because the email renders in a sandboxed frame that none of our CSS reaches.
const CHIP_STYLE = 'background:#fef3c7;color:#92400e;border-radius:4px;padding:0 4px'

/** Turns the fenced labels in rendered html into chips, and drops the fences inside attributes. */
export function withUnresolvedChips(html: string): string {
    if (!html.includes(CHIP_START)) {
        return html
    }
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('*').forEach((element) => {
        for (const attribute of Array.from(element.attributes)) {
            if (attribute.value.includes(CHIP_START)) {
                attribute.value = attribute.value.replace(CHIP_PATTERN, '$1')
            }
        }
    })
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
    const textNodes: Text[] = []
    while (walker.nextNode()) {
        textNodes.push(walker.currentNode as Text)
    }
    for (const node of textNodes.filter((text) => text.data.includes(CHIP_START))) {
        const parts = splitUnresolved(node.data).map((part, index) => {
            if (index % 2 === 0) {
                return doc.createTextNode(part)
            }
            const chip = doc.createElement('span')
            chip.setAttribute('style', CHIP_STYLE)
            chip.textContent = part
            return chip
        })
        node.replaceWith(...parts)
    }
    const doctype = doc.doctype ? new XMLSerializer().serializeToString(doc.doctype) : ''
    return doctype + doc.documentElement.outerHTML
}

/** The person properties the templates read, for the custom person form. */
export function personPropertiesUsed(templates: string[]): string[] {
    const keys = templates.flatMap((template) =>
        Array.from(template.matchAll(/\bperson\.properties\.([A-Za-z0-9_$]+)/g), (match) => match[1])
    )
    return Array.from(new Set(keys))
}
