import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { accessControlActivityDescriber } from './accessControlActivityDescriber'

describe('accessControlActivityDescriber', () => {
    const makeLogItem = (
        activity: string,
        context: Record<string, any>,
        changes: ActivityChange[] | null = null
    ): ActivityLogItem => ({
        user: { first_name: 'Grace', last_name: 'Hopper', email: 'grace@example.com' },
        activity,
        created_at: '2026-10-23T00:00:00Z',
        scope: ActivityScope.ACCESS_CONTROL,
        detail: {
            merge: null,
            trigger: null,
            changes,
            name: null,
            context: {
                resource: 'warehouse_table',
                resource_id: '0190a1b2',
                access_level: 'viewer',
                role_id: null,
                organization_member_id: null,
                ...context,
            },
        },
    })

    it.each([
        [
            'a grant to a role',
            makeLogItem('created', { role_id: 'role-1' }),
            'Grace Hopper set access for a role to viewer on warehouse table 0190a1b2',
        ],
        [
            'a level change for a member',
            makeLogItem('updated', { organization_member_id: 'member-1', access_level: 'editor' }, [
                {
                    type: ActivityScope.ACCESS_CONTROL,
                    action: 'changed',
                    field: 'access_level',
                    before: 'viewer',
                    after: 'editor',
                },
            ]),
            'Grace Hopper changed access for a member from viewer to editor on warehouse table 0190a1b2',
        ],
        [
            'a removed default for every object of a resource',
            makeLogItem('deleted', { resource: 'dashboard', resource_id: null, access_level: 'none' }),
            'Grace Hopper removed the access rule for everyone on every dashboard',
        ],
        [
            'a project rule',
            makeLogItem('created', {
                resource: 'project',
                resource_id: '2',
                access_level: 'admin',
                organization_member_id: 'member-1',
            }),
            'Grace Hopper set access for a member to admin on this project',
        ],
    ])('describes %s', (_name, logItem, expected) => {
        const { description } = accessControlActivityDescriber(logItem)
        const { container } = render(<>{description}</>)
        expect(container.textContent).toEqual(expected)
    })
})
