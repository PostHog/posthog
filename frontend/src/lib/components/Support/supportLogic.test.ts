import posthog from 'posthog-js'

import { OrganizationBasicType, Region, TeamPublicType } from '~/types'

import { getPublicSupportSnippet } from './supportLogic'

describe('supportLogic snippet helpers', () => {
    const mockedGetReplayUrl = posthog.get_session_replay_url as jest.Mock
    const organization = { id: 'org-1', name: 'Test org' } as OrganizationBasicType
    const team = { id: 42 } as TeamPublicType

    beforeEach(() => {
        mockedGetReplayUrl.mockReset()
    })

    it('rewrites the session line to the internal golink for staff triage', () => {
        mockedGetReplayUrl.mockReturnValue(`${window.location.origin}/replay/abc?t=30`)
        const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
        expect(snippet).toContain('Session: http://go/session/abc?t=30')
        expect(snippet).not.toContain(`${window.location.origin}/replay/`)
    })

    it('omits the session line when there is no recording', () => {
        mockedGetReplayUrl.mockReturnValue(undefined)
        const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
        expect(snippet).not.toContain('Session:')
    })

    it('marks the admin line as internal', () => {
        mockedGetReplayUrl.mockReturnValue(undefined)
        const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
        expect(snippet).toContain('Admin (internal): http://go/adminOrg')
    })
})
