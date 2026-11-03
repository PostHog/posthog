import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { commentsLogic } from './commentsLogic'
import { linkSlackThreadLogic } from './linkSlackThreadLogic'

const PROPS = { scope: ActivityScope.TICKET, item_id: 'ticket-1' }
const LINK = 'https://example.slack.com/archives/C0123ABCDEF/p1767225636123456'

describe('linkSlackThreadLogic', () => {
    let logic: ReturnType<typeof linkSlackThreadLogic.build>
    let discussion: ReturnType<typeof commentsLogic.build>
    let linkBody: Record<string, any> | null
    let linkResponse: [number, Record<string, any>]

    beforeEach(() => {
        linkBody = null
        linkResponse = [201, { id: 'root' }]
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/comments': { results: [] },
                '/api/organizations/@current/members/': { results: [] },
            },
            post: {
                '/api/projects/:team_id/comments/link_slack_thread': async ({ request }) => {
                    linkBody = (await request.json()) as Record<string, any>
                    return linkResponse
                },
            },
        })
        discussion = commentsLogic(PROPS)
        discussion.mount()
        logic = linkSlackThreadLogic(PROPS)
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        discussion.unmount()
    })

    it('links the thread to its own discussion, refreshes that discussion and closes', async () => {
        logic.actions.openModal()
        logic.actions.setIntegrationId(9)
        logic.actions.setUrl(`  ${LINK} `)

        // A refresh, not a load: the linked opening comment can sort mid-list, so the reader stays put
        await expectLogic(logic, () => logic.actions.submit())
            .toDispatchActions([
                'submit',
                discussion.actionTypes.addLinkedSlackThread,
                discussion.actionTypes.refreshComments,
                'closeModal',
            ])
            .toNotHaveDispatchedActions([discussion.actionTypes.loadComments])
            .toMatchValues({ isOpen: false, isSubmitting: false, error: null })
        expect(linkBody).toEqual({ scope: 'Ticket', item_id: 'ticket-1', integration_id: 9, url: LINK })
    })

    it("keeps the modal open with PostHog's reason when it refuses, and clears the reason on a new link", async () => {
        linkResponse = [400, { type: 'validation_error', detail: 'Only internal channels can be linked.' }]
        logic.actions.openModal()
        logic.actions.setIntegrationId(9)
        logic.actions.setUrl(LINK)

        await expectLogic(logic, () => logic.actions.submit())
            .toDispatchActions(['submit', 'submitFailure'])
            .toMatchValues({ isOpen: true, isSubmitting: false, error: 'Only internal channels can be linked.' })

        logic.actions.setUrl('https://example.slack.com/archives/C1/p1')
        expect(logic.values.error).toBeNull()
    })

    it('leaves a reopened modal alone when an earlier request finishes', async () => {
        let release: () => void = () => {}
        const released = new Promise<void>((resolve) => {
            release = resolve
        })
        useMocks({
            post: {
                '/api/projects/:team_id/comments/link_slack_thread': async () => {
                    await released
                    return [400, { type: 'validation_error', detail: 'That channel is shared.' }]
                },
            },
        })
        logic.actions.openModal()
        logic.actions.setIntegrationId(9)
        logic.actions.setUrl(LINK)
        logic.actions.submit()
        logic.actions.closeModal()

        logic.actions.openModal()
        logic.actions.setUrl('https://example.slack.com/archives/C1/p1767225700000100')
        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            isOpen: true,
            error: null,
            url: 'https://example.slack.com/archives/C1/p1767225700000100',
        })
    })

    it('belongs to one discussion, so another discussion on screen stays closed', () => {
        const other = linkSlackThreadLogic({ scope: ActivityScope.INSIGHT, item_id: '12345' })
        other.mount()

        logic.actions.openModal()

        expect(other.values.isOpen).toBe(false)
        other.unmount()
    })
})
