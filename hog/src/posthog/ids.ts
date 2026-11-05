import { z } from 'zod'

import { parser } from '@/core/schema'

function projectIdErrorMessage(issue: { input?: unknown }): string {
    return `The project ID must be a number, but it is "${String(issue.input)}". Pass a numeric project ID, like 12345.`
}

// PostHog sends a project ID as a number and hog keeps it as text, as it appears in URLs.
export const ProjectIdSchema = z
    .union([z.string(), z.int()], { error: 'The project ID must be a number. Pass a numeric project ID, like 12345.' })
    .transform(String)
    .pipe(z.string().regex(/^\d+$/, { error: projectIdErrorMessage }))
    .brand<'ProjectId'>()

export type ProjectId = z.output<typeof ProjectIdSchema>

function organizationIdErrorMessage(issue: { input?: unknown }): string {
    return `The organization ID must be a UUID, but it is "${String(issue.input)}". Pass the organization's UUID, like 0188f5b4-1d2a-7000-8a1c-3f6e2b9c7d10.`
}

export const OrganizationIdSchema = z.guid({ error: organizationIdErrorMessage }).brand<'OrganizationId'>()

export type OrganizationId = z.output<typeof OrganizationIdSchema>

export const parseProjectId = parser(ProjectIdSchema, {
    code: 'invalid_project_id',
    hint: 'Use the number in your project URL, like the 2 in https://us.posthog.com/project/2, or copy it from https://app.posthog.com/settings/project-details',
})

export const parseOrganizationId = parser(OrganizationIdSchema, {
    code: 'invalid_organization_id',
    hint: 'Copy the organization ID from Settings > Organization in PostHog: https://app.posthog.com/settings/organization',
})
