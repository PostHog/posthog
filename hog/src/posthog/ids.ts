import { z } from 'zod'

import { parser } from '@/core/schema'

function projectIdProblem(issue: { input?: unknown }): string {
    return `The project ID must be a number, but it is "${String(issue.input)}".`
}

// PostHog sends a project ID as a number and hog keeps it as text, as it appears in URLs.
export const ProjectIdSchema = z
    .union([z.string(), z.int()], { error: 'The project ID must be a number.' })
    .transform(String)
    .pipe(z.string().regex(/^\d+$/, { error: projectIdProblem }))
    .brand<'ProjectId'>()

export type ProjectId = z.output<typeof ProjectIdSchema>

export const OrganizationIdSchema = z
    .guid({ error: (issue) => `The organization ID must be a UUID, but it is "${String(issue.input)}".` })
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
