import { addGroupProperties } from '../../../src/worker/ingestion/groups'

describe('addGroupProperties()', () => {
    let mockGroupTypeManager: any

    beforeEach(() => {
        const lookup: Record<string, number | null> = {
            organization: 0,
            project: 1,
            foobar: null,
        }
        mockGroupTypeManager = {
            fetchGroupTypeIndex: jest.fn().mockImplementation((teamId, key) => lookup[key]),
        }
    })

    it('does nothing if no group properties', async () => {
        expect(await addGroupProperties(2, { foo: 'bar' }, mockGroupTypeManager)).toEqual({ foo: 'bar' })

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

        expect(await addGroupProperties(2, properties, mockGroupTypeManager)).toEqual({
            foo: 'bar',
            $groups: {
                organization: 'PostHog',
                project: 'web',
                foobar: 'afsafa',
            },
            $group_0: 'PostHog',
            $group_1: 'web',
        })

        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledWith(2, 'organization')
        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledWith(2, 'project')
        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledWith(2, 'foobar')
    })
})
