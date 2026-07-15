import api, { ApiConfig } from 'lib/api'

import { trackFileSystemLogView } from './useFileSystemLogView'

describe('trackFileSystemLogView', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        ApiConfig.setCurrentTeamId(null as unknown as number)
    })

    it('does not throw when the team-scoped request throws', () => {
        // Reproduces the reported crash: a team-scoped call throwing synchronously ("Team ID is not
        // known.") must be swallowed rather than escape as an uncaught exception from this
        // fire-and-forget telemetry helper.
        ApiConfig.setCurrentTeamId(1)
        jest.spyOn(api.fileSystemLogView, 'create').mockImplementation(() => {
            throw new Error('Team ID is not known.')
        })

        expect(() => trackFileSystemLogView({ type: 'scene', ref: 'dashboards' })).not.toThrow()
    })

    it('skips the request when no team ID is set', () => {
        const createSpy = jest.spyOn(api.fileSystemLogView, 'create')

        trackFileSystemLogView({ type: 'scene', ref: 'dashboards' })

        expect(createSpy).not.toHaveBeenCalled()
    })
})
