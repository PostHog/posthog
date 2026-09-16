import type { MemberProjectAccessEntryApi } from 'products/access_control/frontend/generated/api.schemas'

import {
    accessibleProjects,
    describeProjectAccessSource,
    orderByActivity,
    projectAccessSourceUrl,
} from './memberProjectAccess'

function entry(
    team_name: string,
    access_level: string,
    resolved: Partial<MemberProjectAccessEntryApi['resolved']> | null = {},
    subject_id: string | null = null
): MemberProjectAccessEntryApi {
    return {
        team_id: team_name.length,
        team_name,
        access_level,
        subject_id,
        resolved: resolved
            ? {
                  access_level,
                  source: 'object',
                  source_subject: 'default',
                  source_resource: 'project',
                  source_resource_id: null,
                  subject_name: null,
                  ...resolved,
              }
            : null,
    }
}

describe('memberProjectAccess', () => {
    it('hides no-access projects and keeps the API order', () => {
        const projects = accessibleProjects([
            entry('App', 'admin'),
            entry('Billing', 'member'),
            entry('Docs', 'member'),
            entry('Marketing', 'none'),
        ])
        expect(projects.map((p) => p.team_name)).toEqual(['App', 'Billing', 'Docs'])
    })

    it.each([
        ['org_admin', null, 'Organization admins always have full access'],
        ['system_default', null, 'No access rules set'],
        ['object', 'member', 'Set for this member'],
        ['object', 'role', 'Based on role Engineering'],
        ['object', 'default', 'Based on project default permissions'],
    ] as const)('describes the %s / %s source', (source, source_subject, expected) => {
        expect(
            describeProjectAccessSource(entry('App', 'admin', { source, source_subject, subject_name: 'Engineering' }))
        ).toBe(expected)
    })

    it.each([
        ['org_admin', null, null, null],
        ['object', 'default', null, 'access_tab=defaults'],
        ['object', 'role', 'role-1', 'access_tab=roles&access_role_id=role-1'],
        ['object', 'member', 'm-1', 'access_tab=members&access_member_id=m-1'],
    ] as const)('links %s / %s to the page of the deciding rule', (source, source_subject, subject_id, expected) => {
        const url = projectAccessSourceUrl(entry('App', 'admin', { source, source_subject }, subject_id), 'm-1')
        if (expected === null) {
            expect(url).toBeNull()
        } else {
            expect(url).toBe(`/project/3/settings/environment-access-control?${expected}`)
        }
    })

    it('orders tags by most recent data, with unknown projects last in API order', () => {
        const ordered = orderByActivity([entry('App', 'admin'), entry('Billing', 'member'), entry('Docs', 'member')], {
            [entry('Billing', 'member').team_id]: {
                team_id: 7,
                freshness: 'live',
                last_data_at: '2026-09-15T00:00:00Z',
                sources: [],
            },
            [entry('Docs', 'member').team_id]: {
                team_id: 4,
                freshness: 'stale',
                last_data_at: '2026-08-01T00:00:00Z',
                sources: [],
            },
        })
        expect(ordered.map((p) => p.team_name)).toEqual(['Billing', 'Docs', 'App'])
    })
})
