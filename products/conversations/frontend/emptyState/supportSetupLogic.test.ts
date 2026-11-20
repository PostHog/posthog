import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { conversationsTicketsList } from 'products/conversations/frontend/generated/api'

import { supportSetupLogic } from './supportSetupLogic'

jest.mock('products/conversations/frontend/generated/api', () => ({
    conversationsTicketsList: jest.fn(),
}))

const mockTicketsList = conversationsTicketsList as jest.MockedFunction<typeof conversationsTicketsList>

function mountWithTeam(conversationsEnabled: boolean): ReturnType<typeof supportSetupLogic.build> {
    initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: conversationsEnabled } as TeamType)
    const logic = supportSetupLogic()
    logic.mount()
    return logic
}

// Guards the three-way ladder into the app-wide setup-status layer: no tickets and support
// off → needs-setup, on without tickets → waiting-for-data, any tickets → has-data whatever
// the toggle says. If the connect or mapping breaks, the gate shows the wrong surface.
describe('supportSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([
        [0, false, 'needs-setup'],
        [0, true, 'waiting-for-data'],
        [1, true, 'has-data'],
        [42, true, 'has-data'],
        // A team that switched support off keeps its tickets, and this list is the only
        // place to read them, so the history has to outrank the toggle.
        [42, false, 'has-data'],
    ])('pushes %i tickets with support enabled=%s as status %s', async (count, enabled, expected) => {
        mockTicketsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = mountWithTeam(enabled)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.CONVERSATIONS }).values.status).toBe(expected)
    })

    it('reports the first ticket once, when it arrives while the setup screen is waiting', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        mockTicketsList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        const logic = mountWithTeam(true)
        await expectLogic(logic).toFinishAllListeners()

        mockTicketsList.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [{ channel_source: 'email', tags: [] }],
        } as any)
        logic.actions.checkSetup()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.checkSetup()
        await expectLogic(logic).toFinishAllListeners()

        const firstTicketCalls = capture.mock.calls.filter(([event]) => event === 'support setup first ticket detected')
        expect(firstTicketCalls).toEqual([
            ['support setup first ticket detected', { channel_source: 'email', is_test: false }],
        ])
    })

    it('polls again after Support turns on without a remount', async () => {
        // Only the poll interval is faked, because kea-test-utils waits on real timeouts.
        jest.useFakeTimers({
            doNotFake: ['setTimeout', 'clearTimeout', 'setImmediate', 'clearImmediate', 'nextTick', 'queueMicrotask'],
        })
        try {
            mockTicketsList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
            const logic = mountWithTeam(false)
            await expectLogic(logic).toFinishAllListeners()
            const status = (): string => productSetupStatusLogic({ productKey: ProductKey.CONVERSATIONS }).values.status
            expect(status()).toBe('needs-setup')

            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, conversations_enabled: true } as TeamType)
            await expectLogic(logic).toFinishAllListeners()
            expect(status()).toBe('waiting-for-data')

            mockTicketsList.mockResolvedValue({ count: 1, next: null, previous: null, results: [] })
            jest.advanceTimersByTime(20000)
            await expectLogic(logic).toFinishAllListeners()
            expect(status()).toBe('has-data')
        } finally {
            jest.useRealTimers()
        }
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockTicketsList.mockRejectedValue(new Error('network down'))
        const logic = mountWithTeam(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.CONVERSATIONS }).values.status).toBe('unknown')
    })
})
