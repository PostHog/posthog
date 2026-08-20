import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { buildTeamScopedPersistenceConfig, buildTeamScopedStorageConfig } from './persistence'

jest.mock('lib/utils/getAppContext')

const mockGetCurrentTeamId = getCurrentTeamId as jest.MockedFunction<typeof getCurrentTeamId>

describe('team-scoped persistence', () => {
    beforeEach(() => {
        mockGetCurrentTeamId.mockReset()
    })

    it.each([
        ['prefix config', () => buildTeamScopedPersistenceConfig('filters__')],
        ['storage config', () => buildTeamScopedStorageConfig('filters')],
    ])('fails closed without a project ID for %s', (_, buildConfig) => {
        mockGetCurrentTeamId.mockImplementation(() => {
            throw new Error('Project ID is not known.')
        })

        expect(buildConfig).toThrow('Project ID is not known.')
    })
})
