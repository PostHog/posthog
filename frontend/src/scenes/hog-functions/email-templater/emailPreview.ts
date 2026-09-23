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
export function renderEmailPreview(template: string, person: EmailPreviewPerson | null): string {
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
        return LiquidRenderer.renderKeepingUnresolved(template, context)
    } catch {
        return template
    }
}

/** The meta fields a preview resolves alongside the body. */
export interface EmailPreviewFields {
    to: string
    subject: string
    preheader: string
}

export interface EmailPreviewResult {
    html: string
    fields: EmailPreviewFields
    /** The expressions still on screen, one entry per variable this person has no value for. */
    unresolvedVariables: string[]
}

/** The authored email, in either of the two shapes the templater stores a recipient in. */
export interface EmailPreviewTemplate {
    subject?: string
    preheader?: string
    to?: string | { email?: string }
}

/** Render the meta fields against a person. The body renders on its own, because it is the slow one. */
export function renderEmailPreviewFields(
    template: EmailPreviewTemplate | null | undefined,
    person: EmailPreviewPerson | null
): EmailPreviewFields {
    // Native email holds the recipient as { email, name }, the legacy email input as a bare
    // template string.
    const to = typeof template?.to === 'string' ? template.to : (template?.to?.email ?? '')
    return {
        to: renderEmailPreview(to, person),
        subject: renderEmailPreview(template?.subject ?? '', person),
        preheader: renderEmailPreview(template?.preheader ?? '', person),
    }
}

/**
 * The expressions a render left on screen, one per variable the person has no value for. Reads
 * the rendered output rather than the template, because only the render knows which tags resolved.
 */
export function unresolvedVariables(rendered: string): string[] {
    return Array.from(rendered.matchAll(/\{\{([\s\S]*?)\}\}/g), (match) => match[1].trim())
}
