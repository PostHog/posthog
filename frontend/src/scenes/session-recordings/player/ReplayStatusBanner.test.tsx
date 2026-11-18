import { TeamPublicType, TeamType } from '~/types'

import { replayOptInStatus } from './ReplayStatusBanner'

const teamWithOptIn = (session_recording_opt_in: boolean): TeamType =>
    ({ id: 1, session_recording_opt_in }) as unknown as TeamType

// The public payload for shared pages carries no replay fields at all.
const publicTeam: TeamPublicType = { id: 1, uuid: 'uuid', name: 'Public', timezone: 'UTC' }

describe('replayOptInStatus', () => {
    it('reports the opt-in once the team is known', () => {
        expect(replayOptInStatus(teamWithOptIn(true), false)).toBe('enabled')
        expect(replayOptInStatus(teamWithOptIn(false), false)).toBe('disabled')
    })

    it('waits while the first team load is in flight', () => {
        expect(replayOptInStatus(null, true)).toBe('loading')
    })

    // teamLogic swallows a failed `api/environments/@current` and resolves with the existing value,
    // so a page that never got a team settles on null with loading false. That must not sit on the
    // skeleton forever, and must not claim replay is off either.
    it('gives up rather than waiting forever when the team never arrives', () => {
        expect(replayOptInStatus(null, false)).toBe('unknown')
    })

    it('stays silent when the team carries no replay fields', () => {
        expect(replayOptInStatus(publicTeam, false)).toBe('unknown')
    })

    it('keeps a settled opt-in while a background refresh runs', () => {
        expect(replayOptInStatus(teamWithOptIn(true), true)).toBe('enabled')
        expect(replayOptInStatus(teamWithOptIn(false), true)).toBe('disabled')
    })
})
