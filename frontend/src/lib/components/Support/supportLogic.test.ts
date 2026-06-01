import posthog from 'posthog-js'

import { OrganizationBasicType, Region, TeamPublicType } from '~/types'

import { getPublicSessionReplayUrl, getPublicSupportSnippet } from './supportLogic'

describe('supportLogic snippet helpers', () => {
    const mockedGetReplayUrl = posthog.get_session_replay_url as jest.Mock
    const organization = { id: 'org-1', name: 'Test org' } as OrganizationBasicType
    const team = { id: 42 } as TeamPublicType

    beforeEach(() => {
        mockedGetReplayUrl.mockReset()
    })

    it('returns the public replay url unchanged', () => {
        mockedGetReplayUrl.mockReturnValue('http://localhost/replay/abc?t=30')
        expect(getPublicSessionReplayUrl()).toEqual('http://localhost/replay/abc?t=30')
    })

    it('returns null when no replay url is available', () => {
        mockedGetReplayUrl.mockReturnValue(undefined)
        expect(getPublicSessionReplayUrl()).toBeNull()
    })

    it('uses the public /replay/ url in the GitHub debug snippet, not the internal golink', () => {
        mockedGetReplayUrl.mockReturnValue('http://localhost/replay/abc?t=30')
        const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
        expect(snippet).toContain('Session: http://localhost/replay/abc?t=30')
        expect(snippet).not.toContain('http://go/session/')
    })

    it('omits the session line when there is no recording', () => {
        mockedGetReplayUrl.mockReturnValue(undefined)
        const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
        expect(snippet).not.toContain('Session:')
    })
})
