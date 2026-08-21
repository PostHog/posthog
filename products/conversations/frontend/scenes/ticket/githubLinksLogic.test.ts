import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    conversationsTicketsGithubLinksCreate,
    conversationsTicketsGithubLinksDestroy,
    conversationsTicketsGithubLinksRetrieve,
} from '../../generated/api'
import type { TicketGithubLinkApi } from '../../generated/api.schemas'
import { githubLinksLogic } from './githubLinksLogic'

jest.mock('../../generated/api', () => ({
    conversationsTicketsGithubLinksRetrieve: jest.fn(),
    conversationsTicketsGithubLinksCreate: jest.fn(),
    conversationsTicketsGithubLinksDestroy: jest.fn(),
}))

const mockRetrieve = conversationsTicketsGithubLinksRetrieve as jest.Mock
const mockCreate = conversationsTicketsGithubLinksCreate as jest.Mock
const mockDestroy = conversationsTicketsGithubLinksDestroy as jest.Mock

function makeLink(overrides: Partial<TicketGithubLinkApi> = {}): TicketGithubLinkApi {
    return {
        id: 'link-1',
        repo: 'PostHog/posthog',
        number: 123,
        link_type: 'issue',
        url: 'https://github.com/PostHog/posthog/issues/123',
        title: null,
        link_state: null,
        created_by: null,
        created_at: '2026-07-25T10:00:00Z',
        ...overrides,
    }
}

describe('githubLinksLogic', () => {
    let logic: ReturnType<typeof githubLinksLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockRetrieve.mockResolvedValue([makeLink()])
        logic = githubLinksLogic({ ticketId: 'ticket-1' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('appends a newly created link and clears the input, but does not duplicate an already-linked one', async () => {
        await expectLogic(logic).toDispatchActions(['loadGithubLinksSuccess'])
        const newLink = makeLink({ id: 'link-2', number: 456, link_type: 'pull_request' })
        mockCreate.mockResolvedValueOnce(newLink)

        logic.actions.setNewLinkUrl('https://github.com/PostHog/posthog/pull/456')
        logic.actions.addGithubLink()
        await expectLogic(logic).toDispatchActions(['addGithubLinkSuccess'])
        expect(logic.values.githubLinks.map((link) => link.id)).toEqual(['link-1', 'link-2'])
        expect(logic.values.newLinkUrl).toEqual('')
        expect(logic.values.linkSubmitting).toEqual(false)

        mockCreate.mockResolvedValueOnce(makeLink())
        logic.actions.setNewLinkUrl('https://github.com/PostHog/posthog/issues/123')
        logic.actions.addGithubLink()
        await expectLogic(logic).toDispatchActions(['addGithubLinkSuccess'])
        expect(logic.values.githubLinks.map((link) => link.id)).toEqual(['link-1', 'link-2'])
    })

    it('keeps the typed URL and the list intact when linking fails', async () => {
        await expectLogic(logic).toDispatchActions(['loadGithubLinksSuccess'])
        mockCreate.mockRejectedValueOnce({ detail: 'Enter a GitHub issue or pull request URL' })

        logic.actions.setNewLinkUrl('https://example.com/not-github')
        logic.actions.addGithubLink()
        await expectLogic(logic).toDispatchActions(['addGithubLinkFailure'])
        expect(logic.values.newLinkUrl).toEqual('https://example.com/not-github')
        expect(logic.values.githubLinks).toHaveLength(1)
        expect(logic.values.linkSubmitting).toEqual(false)
    })

    it('removes a link only after the server confirms the delete', async () => {
        await expectLogic(logic).toDispatchActions(['loadGithubLinksSuccess'])
        mockDestroy.mockRejectedValueOnce(new Error('boom'))
        logic.actions.removeGithubLink('link-1')
        await expectLogic(logic).toDispatchActions(['removeGithubLinkFailure'])
        expect(logic.values.githubLinks).toHaveLength(1)
        expect(logic.values.removingLinkId).toBeNull()

        mockDestroy.mockResolvedValueOnce(undefined)
        logic.actions.removeGithubLink('link-1')
        await expectLogic(logic).toDispatchActions(['removeGithubLinkSuccess'])
        expect(logic.values.githubLinks).toEqual([])
    })
})
