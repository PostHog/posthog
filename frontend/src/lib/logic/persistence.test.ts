import { getCurrentTeamId, getCurrentUserId } from 'lib/utils/getAppContext'

import {
    buildTeamScopedPersistenceConfig,
    buildTeamScopedStorageConfig,
    buildUserScopedPersistenceConfig,
} from './persistence'

jest.mock('lib/utils/getAppContext')

const mockGetCurrentTeamId = getCurrentTeamId as jest.MockedFunction<typeof getCurrentTeamId>
const mockGetCurrentUserId = getCurrentUserId as jest.MockedFunction<typeof getCurrentUserId>

describe('persistence scoping', () => {
    beforeEach(() => {
        mockGetCurrentTeamId.mockReset()
        mockGetCurrentUserId.mockReset()
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
        mockGetCurrentUserId.mockReturnValue('user-1')
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

    it('fails closed without a user ID', () => {
        mockGetCurrentUserId.mockImplementation(() => {
            throw new Error('User ID is not known.')
        })

        expect(() => buildUserScopedPersistenceConfig('filters__')).toThrow('User ID is not known.')
    })
})
