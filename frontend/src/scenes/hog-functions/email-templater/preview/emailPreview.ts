import { LiquidRenderer } from 'lib/utils/liquid'

/** The person values a preview renders against, shaped like the worker's `person` global. */
export interface EmailPreviewPerson {
    id: string
    properties: Record<string, any>
    /** The event that would have triggered the send, for templates that read `event`. */
    event?: { properties: Record<string, any> }
}

/**
 * Render one templated email field against a person, the way the send will.
 *
 * Returns the template unchanged when it can't be parsed, because a preview must never be the
 * thing that breaks the review step.
 */
// The worker's output budget, from nodejs/src/cdp/utils/liquid.ts: real bodies reach megabytes of inlined images.
const MAX_PREVIEW_LENGTH = 10_000_000

// Anyone who can send events can set a person value, and one carrying the fences that mark a missing value
// would fake that marker in the preview.
function withoutFences(value: unknown): any {
    if (typeof value === 'string') {
        return value.replace(/[\uE000\uE001]/g, '')
    }
    if (Array.isArray(value)) {
        return value.map(withoutFences)
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value).map(([key, entry]) => [withoutFences(key), withoutFences(entry)])
        )
    }
    return value
}

export function renderEmailPreview(
    template: string,
    person: EmailPreviewPerson | null,
    markUnresolved?: (source: string) => string,
    plainText = false
): string {
    if (!template || !person) {
        return template
    }
    const context = {
        person: {
            id: person.id,
            properties: withoutFences(person.properties),
        },
        event: person.event,
        // Injected by the email service per recipient. Stand it in so a preview doesn't report the
        // unsubscribe link every marketing email carries as a missing variable.
        unsubscribe_url: '#unsubscribe',
        now: new Date(),
    }
    try {
        const rendered = LiquidRenderer.renderKeepingUnresolved(template, context, markUnresolved, plainText)
        // Render budgets don't bound output size, and the chip and link passes parse the result as a document.
        return rendered.length > MAX_PREVIEW_LENGTH ? template : rendered
    } catch {
        return template
    }
}

// Private-use characters fence each unresolved tag's label, so the html and the plain-text previews
// can each turn them into a chip after rendering, without the marker ever reading as Liquid.
const CHIP_START = '\uE000'
const CHIP_END = '\uE001'
const CHIP_PATTERN = /\uE000([^\uE000\uE001]*)\uE001/g

/** Renders the template against the person, fencing each tag the person has no value for. */
export function renderEmailPreviewMarked(
    template: string,
    person: EmailPreviewPerson | null,
    plainText = false
): string {
    return renderEmailPreview(
        template,
        person,
        (source) => `${CHIP_START}${unresolvedLabel(source)}${CHIP_END}`,
        plainText
    )
}

/** "{{ person.properties.first_name }}" reads as "first name". */
function unresolvedLabel(source: string): string {
    const path = source.replace(/^\{\{-?|-?\}\}$/g, '').trim()
    return (path.split('.').pop() ?? path).replace(/[_$]/g, ' ').trim()
}

/** How many different values the person is missing, however often the templates use each one. */
export function countUnresolved(...rendered: string[]): number {
    return new Set(rendered.flatMap((text) => Array.from(text.matchAll(CHIP_PATTERN), (match) => match[1]))).size
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

/** The person and event properties the templates read, as paths like `event.properties.plan`, for the custom person form. */
export function propertiesUsed(templates: string[]): string[] {
    const paths = templates.flatMap((template) =>
        // The editor writes `person.properties["renews on"]` for a key that isn't a plain name.
        Array.from(
            template.matchAll(/\b(person|event)\.properties(?:\.([A-Za-z0-9_$]+)|\[\s*["']([^"']+)["']\s*\])/g),
            (match) => `${match[1]}.properties.${match[2] ?? match[3]}`
        )
    )
    return Array.from(new Set(paths))
}

/** Renders as plain text, with each missing value read out as its label, for one-line summaries. */
export function renderEmailPreviewText(template: string, person: EmailPreviewPerson | null): string {
    return splitUnresolved(renderEmailPreviewMarked(template, person, true)).join('')
}
