import { Team } from '~/src/types'

import { addGroupProperties } from '../../../src/worker/ingestion/groups'

describe('addGroupProperties()', () => {
    let mockGroupTypeManager: any
    let mockTeam: Team

    beforeEach(() => {
        mockTeam = {
            id: 2,
            root_team_id: 2,
        } as Team
        const lookup: Record<string, number | null> = {
            organization: 0,
            project: 1,
            foobar: null,
        }
        mockGroupTypeManager = {
            fetchGroupTypeIndex: jest.fn().mockImplementation((team, key) => lookup[key]),
        }
    })

    it('does nothing if no group properties', async () => {
        expect(await addGroupProperties(mockTeam, { foo: 'bar' }, mockGroupTypeManager)).toEqual({
            foo: 'bar',
        })

        expect(mockGroupTypeManager.fetchGroupTypeIndex).not.toHaveBeenCalled()
    })

    it('sets group properties as needed', async () => {
        const properties = {
            foo: 'bar',
            $groups: {
                organization: 'PostHog',
                project: 'web',
                foobar: 'afsafa',
            },
        }

        expect(await addGroupProperties(mockTeam, properties, mockGroupTypeManager)).toEqual({
            foo: 'bar',
            $groups: {
                organization: 'PostHog',
                project: 'web',
                foobar: 'afsafa',
            },
            $group_0: 'PostHog',
            $group_1: 'web',
        })

        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledWith(mockTeam, 'organization')
        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledWith(mockTeam, 'project')
        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledWith(mockTeam, 'foobar')
    })
})
