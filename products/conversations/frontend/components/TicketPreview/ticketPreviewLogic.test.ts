import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { conversationsTicketsMessagesList } from '../../generated/api'
import { ticketPreviewLogic } from './ticketPreviewLogic'

jest.mock('../../generated/api', () => ({
    conversationsTicketsMessagesList: jest.fn(),
}))

const messagesList = conversationsTicketsMessagesList as jest.Mock

describe('ticketPreviewLogic', () => {
    let logic: ReturnType<typeof ticketPreviewLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // The preview loads on mount, so the failure must be set up before mounting.
    const mountWith = (rejection: unknown): void => {
        messagesList.mockRejectedValue(rejection)
        logic = ticketPreviewLogic({ ticketId: 'ticket-1' })
        logic.mount()
    }

    // A single flaky 503 on a ticket used to open a fresh, ungroupable error tracking issue for
    // every ticket, even though the card degrades to its error state. Transient transport failures
    // must reach the error state without being reported.
    it.each([
        ['a 5xx response', new ApiError('Non-OK response', 503)],
        ['an aborted fetch', new DOMException('The operation was aborted', 'AbortError')],
    ])('shows the error state without reporting %s', async (_desc, thrown) => {
        mountWith(thrown)

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                preview: { firstMessages: [], lastMessage: null, hiddenCount: 0, error: true },
            })

        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('reports genuinely unexpected failures', async () => {
        const unexpected = new TypeError('unexpected')
        mountWith(unexpected)

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                preview: { firstMessages: [], lastMessage: null, hiddenCount: 0, error: true },
            })

        expect(posthog.captureException).toHaveBeenCalledWith(unexpected)
    })
})
