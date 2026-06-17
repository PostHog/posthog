import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'
import { wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

// The detector polls a REST endpoint from afterMount and the stream logic builds an SSE
// URL on connect; stub both so mounting the tracker (which connects them) never hits the
// network or a missing import during these tests.
jest.mock('products/wizard/frontend/generated/api', () => ({
    wizardSessionsLatestRetrieve: jest.fn().mockResolvedValue(null),
    getWizardSessionsStreamRetrieveUrl: jest.fn(() => '/mock/wizard/stream'),
}))

const WORKFLOW_ID = 'posthog-integration'
const ONE_HOUR_MS = 60 * 60 * 1000

// jsdom has no EventSource; the stream logic's connect() constructs one. A no-op stub
// keeps connect() inert so the tracker drives state purely through sessionUpdated().
beforeAll(() => {
    ;(global as any).EventSource = class {
        static readonly CONNECTING = 0
        static readonly OPEN = 1
        static readonly CLOSED = 2
        readyState = 0
        onopen: ((ev: Event) => void) | null = null
        onmessage: ((ev: MessageEvent) => void) | null = null
        onerror: ((ev: Event) => void) | null = null
        close(): void {}
    }
})

function makeSession(overrides: Partial<WizardSessionDTOApi> = {}): WizardSessionDTOApi {
    const nowIso = new Date().toISOString()
    return {
        session_id: 'sess-1',
        team_id: 997,
        workflow_id: WORKFLOW_ID,
        skill_id: 'nextjs',
        started_at: nowIso,
        run_phase: 'running',
        tasks: [],
        event_plan: null,
        error: null,
        created_at: nowIso,
        updated_at: nowIso,
        is_stale: false,
        ...overrides,
    }
}

describe('wizardProgressTrackerLogic', () => {
    let logic: ReturnType<typeof wizardProgressTrackerLogic.build>
    let streamLogic: ReturnType<typeof wizardSessionStreamLogic.build>
    let detector: ReturnType<typeof wizardActiveSessionDetectorLogic.build>

    beforeEach(() => {
        initKeaTests()
        streamLogic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID })
        detector = wizardActiveSessionDetectorLogic()
        logic = wizardProgressTrackerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('arms the detector and marks current when a fresh running session arrives', async () => {
        await expectLogic(detector, () => {
            streamLogic.actions.sessionUpdated(makeSession({ run_phase: 'running' }))
        }).toDispatchActions(['markActive'])

        await expectLogic(logic).toMatchValues({ sessionIsCurrent: true })
        await expectLogic(detector).toMatchValues({ hasActiveSession: true, shouldStream: true })
    })

    it('defers teardown (not immediate) when a running session transitions to completed', async () => {
        streamLogic.actions.sessionUpdated(makeSession({ run_phase: 'running' }))
        await expectLogic(detector).toMatchValues({ hasActiveSession: true })

        // running -> completed: the prior session was eligible, the new one is terminal,
        // so teardown is scheduled behind the grace window rather than firing now.
        await expectLogic(detector, () => {
            streamLogic.actions.sessionUpdated(makeSession({ run_phase: 'completed' }))
        })
            .toDispatchActions(['scheduleMarkInactive'])
            .toNotHaveDispatchedActions(['markInactive'])
        await expectLogic(detector).toMatchValues({ hasActiveSession: true })
    })

    it('does not re-arm the detector for a session past the max lifetime (single-user INC-886)', async () => {
        // A wedged CLI keeps heartbeating updated_at (fresh) but started_at is past the
        // 1h lifetime cap, so the session is ineligible and must not re-open the stream.
        const pastCap = makeSession({
            run_phase: 'running',
            started_at: new Date(Date.now() - 2 * ONE_HOUR_MS).toISOString(),
            updated_at: new Date().toISOString(),
        })

        await expectLogic(detector, () => {
            streamLogic.actions.sessionUpdated(pastCap)
        }).toNotHaveDispatchedActions(['markActive'])
        await expectLogic(detector).toMatchValues({ hasActiveSession: false, shouldStream: false })
    })
})
