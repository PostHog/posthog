import { z } from 'zod'

import { parser } from '@/core/schema'

// PostHog takes `@current` in place of an ID, for the project or organization the key belongs to.
const CURRENT = '@current'

function projectIdProblem(issue: { input?: unknown }): string {
    return `The project ID must be a number or ${CURRENT}, but it is "${String(issue.input)}".`
}

// PostHog sends a project ID as a number and hog keeps it as text, as it appears in URLs.
export const ProjectIdSchema = z
    .union([z.string(), z.int()], { error: `The project ID must be a number or ${CURRENT}.` })
    .transform(String)
    .pipe(z.string().regex(/^(\d+|@current)$/, { error: projectIdProblem }))
    .brand<'ProjectId'>()

export type ProjectId = z.output<typeof ProjectIdSchema>

function organizationIdProblem(issue: { input?: unknown }): string {
    return `The organization ID must be a UUID or ${CURRENT}, but it is "${String(issue.input)}".`
}

export const OrganizationIdSchema = z
    .union([z.guid({ error: organizationIdProblem }), z.literal(CURRENT, { error: organizationIdProblem })], {
        error: organizationIdProblem,
    })
    .brand<'OrganizationId'>()

export type OrganizationId = z.output<typeof OrganizationIdSchema>

export const parseProjectId = parser(ProjectIdSchema, {
    code: 'invalid_project_id',
    hint: 'Use the number in your project URL, like the 2 in https://us.posthog.com/project/2.',
})

export const parseOrganizationId = parser(OrganizationIdSchema, {
    code: 'invalid_organization_id',
    hint: 'Copy the organization ID from Settings > Organization in PostHog.',
})
