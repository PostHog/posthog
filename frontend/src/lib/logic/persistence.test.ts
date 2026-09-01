import { getCurrentTeamId, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'

import {
    buildTeamScopedPersistenceConfig,
    buildTeamScopedStorageConfig,
    buildUserScopedPersistenceConfig,
} from './persistence'

jest.mock('lib/utils/getAppContext')

const mockGetCurrentTeamId = getCurrentTeamId as jest.MockedFunction<typeof getCurrentTeamId>
const mockGetCurrentUserIdOrNone = getCurrentUserIdOrNone as jest.MockedFunction<typeof getCurrentUserIdOrNone>

describe('persistence scoping', () => {
    beforeEach(() => {
        mockGetCurrentTeamId.mockReset()
        mockGetCurrentUserIdOrNone.mockReset()
    })

    it.each([
        ['prefix config', () => buildTeamScopedPersistenceConfig('filters__')],
        ['storage config', () => buildTeamScopedStorageConfig('filters')],
        ['user prefix config', () => buildUserScopedPersistenceConfig('filters__')],
    ])('fails closed without a project ID for %s', (_, buildConfig) => {
        mockGetCurrentTeamId.mockImplementation(() => {
            throw new Error('Project ID is not known.')
        })

        expect(buildConfig).toThrow('Project ID is not known.')
    })

    it('scopes persisted values to the current user and project', () => {
        mockGetCurrentUserIdOrNone.mockReturnValue('user-1')
        mockGetCurrentTeamId.mockReturnValue(2)

        expect(buildUserScopedPersistenceConfig('filters__')).toEqual({
            persist: true,
            prefix: 'user-1__2__filters__',
        })

        mockGetCurrentTeamId.mockReturnValue(3)

        expect(buildUserScopedPersistenceConfig('filters__')).toEqual({
            persist: true,
            prefix: 'user-1__3__filters__',
        })
    })

    it('uses an anonymous key when no user ID is available', () => {
        mockGetCurrentUserIdOrNone.mockReturnValue(null)
        mockGetCurrentTeamId.mockReturnValue(2)

        expect(buildUserScopedPersistenceConfig('filters__')).toEqual({
            persist: true,
            prefix: 'anonymous__2__filters__',
        })
    })
})
