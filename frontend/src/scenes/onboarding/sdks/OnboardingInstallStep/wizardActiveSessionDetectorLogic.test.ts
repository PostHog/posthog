import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { wizardSessionsLatestRetrieve } from 'products/wizard/frontend/generated/api'
import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import { isSessionActive, wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'

jest.mock('products/wizard/frontend/generated/api', () => ({
    wizardSessionsLatestRetrieve: jest.fn(),
}))

const mockLatestRetrieve = wizardSessionsLatestRetrieve as jest.Mock

function makeSession(overrides: Partial<WizardSessionDTOApi> = {}): WizardSessionDTOApi {
    return {
        session_id: 'sess-1',
        team_id: 997,
        workflow_id: 'posthog-integration',
        skill_id: 'install',
        started_at: new Date().toISOString(),
        run_phase: 'running',
        tasks: [],
        event_plan: null,
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        is_stale: false,
        ...overrides,
    }
}

describe('wizardActiveSessionDetectorLogic', () => {
    let logic: ReturnType<typeof wizardActiveSessionDetectorLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockLatestRetrieve.mockReset()
        logic = wizardActiveSessionDetectorLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('isSessionActive', () => {
        it('treats a running, fresh session as active', () => {
            expect(isSessionActive(makeSession({ run_phase: 'running' }))).toBe(true)
        })

        it('treats a null session as inactive', () => {
            expect(isSessionActive(null)).toBe(false)
        })

        it('treats terminal phases as inactive', () => {
            expect(isSessionActive(makeSession({ run_phase: 'completed' }))).toBe(false)
            expect(isSessionActive(makeSession({ run_phase: 'error' }))).toBe(false)
        })

        it('treats a server-flagged stale session as inactive', () => {
            expect(isSessionActive(makeSession({ is_stale: true }))).toBe(false)
        })

        it('treats a session past the max lifetime as inactive', () => {
            const startedAt = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
            expect(isSessionActive(makeSession({ started_at: startedAt }))).toBe(false)
        })
    })

    it('marks active when the poll returns a live session', async () => {
        mockLatestRetrieve.mockResolvedValue(makeSession({ run_phase: 'running' }))

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['markActive'])
            .toMatchValues({ hasActiveSession: true, shouldStream: true })
    })

    it('stays inactive when the poll returns no session (204/null)', async () => {
        mockLatestRetrieve.mockResolvedValue(null)

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['markInactive'])
            .toMatchValues({ hasActiveSession: false, shouldStream: false })
    })

    it('permanently disables the detector on a 401', async () => {
        mockLatestRetrieve.mockRejectedValue(new ApiError('unauthorized', 401))

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['markPermanentlyDisabled'])
            .toMatchValues({ permanentlyDisabled: true })

        // A permanently disabled detector swallows further polls without calling the endpoint.
        const callsAfterDisable = mockLatestRetrieve.mock.calls.length
        await expectLogic(logic, () => {
            logic.actions.check()
        }).toFinishAllListeners()
        expect(mockLatestRetrieve.mock.calls.length).toBe(callsAfterDisable)
    })

    it('permanently disables the detector on a 403', async () => {
        mockLatestRetrieve.mockRejectedValue(new ApiError('forbidden', 403))

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['markPermanentlyDisabled'])
            .toMatchValues({ permanentlyDisabled: true })
    })

    it('does NOT permanently disable on a 404 (transient deploy-window route gap)', async () => {
        mockLatestRetrieve.mockRejectedValue(new ApiError('not found', 404))

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['setLastError'])
            .toNotHaveDispatchedActions(['markPermanentlyDisabled'])
            .toMatchValues({ permanentlyDisabled: false })
    })

    it('defers teardown (scheduleMarkInactive) when an active session goes terminal', async () => {
        logic.actions.markActive()
        await expectLogic(logic).toMatchValues({ hasActiveSession: true })

        mockLatestRetrieve.mockResolvedValue(makeSession({ run_phase: 'completed' }))

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['scheduleMarkInactive'])
            .toNotHaveDispatchedActions(['markInactive'])
            // Teardown is deferred behind the grace window, so the stream stays up for now.
            .toMatchValues({ hasActiveSession: true, shouldStream: true })
    })
})
