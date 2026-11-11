import { z } from 'zod'

import { parseOrThrow, type ParseFailure } from '@/core/schema'

// PostHog sends a project ID as a number and hog keeps it as text, as it appears in URLs. The
// messages leave out the value, because a user who pastes a token into the wrong flag would see
// it in logs.
const PROJECT_ID_ERROR = 'The project ID must be a number. Pass a numeric project ID, like 12345.'

export const ProjectIdSchema = z
    .union([z.string(), z.int()], { error: PROJECT_ID_ERROR })
    .transform(String)
    .pipe(z.string().regex(/^\d+$/, { error: PROJECT_ID_ERROR }))
    // Without leading zeros, so "02" and "2" name the same login.
    .transform((id) => id.replace(/^0+(?=\d)/, ''))
    .brand<'ProjectId'>()

export type ProjectId = z.output<typeof ProjectIdSchema>

export const OrganizationIdSchema = z
    .guid({
        error: "The organization ID must be a UUID. Pass the organization's UUID, like 0188f5b4-1d2a-7000-8a1c-3f6e2b9c7d10.",
    })
    .brand<'OrganizationId'>()

export type OrganizationId = z.output<typeof OrganizationIdSchema>

export function parseProjectId(raw: unknown, failure?: Partial<ParseFailure>): ProjectId {
    return parseOrThrow(ProjectIdSchema, raw, {
        code: 'invalid_project_id',
        hint: 'Use the number in your project URL, like the 2 in https://us.posthog.com/project/2, or copy it from https://app.posthog.com/settings/project-details',
        ...failure,
    })
}

export function parseOrganizationId(raw: unknown, failure?: Partial<ParseFailure>): OrganizationId {
    return parseOrThrow(OrganizationIdSchema, raw, {
        code: 'invalid_organization_id',
        hint: 'Copy the organization ID from Settings > Organization in PostHog: https://app.posthog.com/settings/organization',
        ...failure,
    })
}
