import { GroupTypeToColumnIndex, ProjectId } from '../../types'
import { addGroupProperties, enrichPropertiesWithGroupTypes } from './groups'

describe('enrichPropertiesWithGroupTypes', () => {
    it.each([
        {
            desc: 'does nothing when no $groups present',
            properties: { foo: 'bar' },
            groupTypes: { org: 0 } as GroupTypeToColumnIndex,
            expected: { foo: 'bar' },
        },
        {
            desc: 'does nothing when $groups is empty',
            properties: { foo: 'bar', $groups: {} },
            groupTypes: { org: 0 } as GroupTypeToColumnIndex,
            expected: { foo: 'bar', $groups: {} },
        },
        {
            desc: 'sets $group_N for known group types',
            properties: { $groups: { org: 'posthog', project: 'web' } },
            groupTypes: { org: 0, project: 1 } as GroupTypeToColumnIndex,
            expected: { $groups: { org: 'posthog', project: 'web' }, $group_0: 'posthog', $group_1: 'web' },
        },
        {
            desc: 'skips group types not in the mapping',
            properties: { $groups: { org: 'posthog', unknown: 'value' } },
            groupTypes: { org: 0 } as GroupTypeToColumnIndex,
            expected: { $groups: { org: 'posthog', unknown: 'value' }, $group_0: 'posthog' },
        },
        {
            desc: 'preserves existing properties',
            properties: { foo: 'bar', $groups: { org: 'posthog' } },
            groupTypes: { org: 2 } as GroupTypeToColumnIndex,
            expected: { foo: 'bar', $groups: { org: 'posthog' }, $group_2: 'posthog' },
        },
    ])('$desc', ({ properties, groupTypes, expected }) => {
        expect(enrichPropertiesWithGroupTypes(properties, groupTypes)).toEqual(expected)
    })
})

describe('addGroupProperties', () => {
    const mockGroupTypeManager = (lookup: Record<string, number | null>) => ({
        fetchGroupTypeIndex: jest
            .fn()
            .mockImplementation((_teamId: number, _projectId: number, key: string) => lookup[key] ?? null),
    })

    it('does nothing if no $groups present', async () => {
        const mgr = mockGroupTypeManager({ org: 0 })

        expect(await addGroupProperties(2, 2 as ProjectId, { foo: 'bar' }, mgr as any)).toEqual({
            foo: 'bar',
        })
        expect(mgr.fetchGroupTypeIndex).not.toHaveBeenCalled()
    })

    it('resolves group types via fetchGroupTypeIndex and sets $group_N', async () => {
        const mgr = mockGroupTypeManager({ organization: 0, project: 1, foobar: null })

        const properties = {
            foo: 'bar',
            $groups: {
                organization: 'PostHog',
                project: 'web',
                foobar: 'afsafa',
            },
        }

        expect(await addGroupProperties(2, 2 as ProjectId, properties, mgr as any)).toEqual({
            foo: 'bar',
            $groups: {
                organization: 'PostHog',
                project: 'web',
                foobar: 'afsafa',
            },
            $group_0: 'PostHog',
            $group_1: 'web',
        })

        expect(mgr.fetchGroupTypeIndex).toHaveBeenCalledWith(2, 2, 'organization')
        expect(mgr.fetchGroupTypeIndex).toHaveBeenCalledWith(2, 2, 'project')
        expect(mgr.fetchGroupTypeIndex).toHaveBeenCalledWith(2, 2, 'foobar')
    })
})
