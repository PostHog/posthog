import { base64Decode, base64Encode } from 'lib/utils/base64'

import { SKILL_DESCRIPTION_MAX_LENGTH, validateSkillName } from 'products/skills/frontend/skillConstants'

import type { ScoutCreateInitialValues } from '../logics/scoutCreateModalLogic'
import { SIGNALS_SCOUT_SKILL_PREFIX } from './scoutRunsWindow'

/**
 * Deep-link payload for pre-filling the scout create modal, e.g. from a template page on
 * posthog.com: `/inbox/config#createScout=<url-safe base64 JSON>`.
 *
 * The payload travels in the URL fragment so it never reaches server logs, mirroring the
 * `posthog-code://plan?plan=<base64>` precedent in the desktop app. Decoding is prefill-only:
 * nothing is created until the user reviews the form and submits it themselves, and the
 * payload can only seed the name/description/body fields — scheduling and emit posture
 * (`config`) are deliberately not accepted from URLs, so a link can never change how or how
 * often anything runs.
 */
export interface ScoutTemplatePayload {
    name?: string
    description?: string
    body?: string
}

/** Whole-payload cap, before decoding. Far above any real template, far below abuse territory. */
const MAX_ENCODED_LENGTH = 16384
const MAX_BODY_LENGTH = 20000

/** Encode a template as a URL-safe base64 fragment value (used by tests and by link authors). */
export function encodeScoutCreateTemplate(template: ScoutTemplatePayload): string {
    return base64Encode(JSON.stringify(template)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * Decode and validate a `#createScout=` fragment value into modal initial values.
 * Returns null for anything malformed, oversized, or empty — callers treat null as
 * "ignore the fragment", never as an error state worth blocking the scene on.
 */
export function decodeScoutCreateTemplate(raw: unknown): ScoutCreateInitialValues | null {
    if (typeof raw !== 'string' || raw.length === 0 || raw.length > MAX_ENCODED_LENGTH) {
        return null
    }

    let parsed: unknown
    try {
        // Accept both base64 alphabets and missing padding, like the desktop deep-link decoder.
        const normalized = raw.replace(/-/g, '+').replace(/_/g, '/')
        const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
        parsed = JSON.parse(base64Decode(padded))
    } catch {
        return null
    }

    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return null
    }

    const { name, description, body } = parsed as Record<string, unknown>
    const cleanDescription =
        typeof description === 'string' ? description.trim().slice(0, SKILL_DESCRIPTION_MAX_LENGTH) : ''
    const cleanBody = typeof body === 'string' ? body.trim().slice(0, MAX_BODY_LENGTH) : ''

    // A link that prefills nothing but a name is indistinguishable from noise — require substance.
    if (!cleanDescription && !cleanBody) {
        return null
    }

    let cleanName = typeof name === 'string' ? name.trim() : ''
    if (cleanName && !cleanName.startsWith(SIGNALS_SCOUT_SKILL_PREFIX)) {
        cleanName = `${SIGNALS_SCOUT_SKILL_PREFIX}${cleanName}`
    }
    if (cleanName && validateSkillName(cleanName)) {
        // Invalid skill name: drop it and let the form's default prefix stand — the user
        // names the scout themselves rather than the link failing outright.
        cleanName = ''
    }

    return {
        ...(cleanName ? { name: cleanName } : {}),
        ...(cleanDescription ? { description: cleanDescription } : {}),
        ...(cleanBody ? { body: cleanBody } : {}),
    }
}
