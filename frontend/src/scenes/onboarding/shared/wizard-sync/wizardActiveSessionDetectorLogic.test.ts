import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'
import type { ProjectType } from '~/types'

import { wizardSessionsLatestRetrieve } from 'products/wizard/frontend/generated/api'
import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import {
    UNAVAILABLE_ROUTE_GRACE_MS,
    isSessionActive,
    wizardActiveSessionDetectorLogic,
} from './wizardActiveSessionDetectorLogic'

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
        pending_input: null,
        handoff_text: null,
        created_by: null,
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

    // The loop this guards: a project scope the user lost access to answers 404 forever, and the
    // detector used to retry it once a minute for the lifetime of the tab, filing an exception each
    // time. A dead scope is knowable from the first answer, so it stops there.
    it('stops polling on the first 404 from a scope that no longer resolves', async () => {
        mockLatestRetrieve.mockRejectedValue(
            new ApiError('not found', 404, undefined, { detail: 'Project not found.' })
        )

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['markPermanentlyDisabled'])
            .toMatchValues({ permanentlyDisabled: true })

        const callsAfterDisable = mockLatestRetrieve.mock.calls.length
        await expectLogic(logic, () => {
            logic.actions.check()
        }).toFinishAllListeners()
        expect(mockLatestRetrieve.mock.calls.length).toBe(callsAfterDisable)
    })

    // A route missing on an old pod mid-rollout looks the same but does come back, so it keeps
    // retrying — until the grace window closes, because a route that never returns must not poll
    // forever either. The window is wall-clock: a project switch or a tab resume can ask for a check
    // every few seconds, and a budget counted in polls would be gone before a deploy finishes.
    describe('an unserved route', () => {
        beforeEach(() => {
            jest.useFakeTimers()
            mockLatestRetrieve.mockRejectedValue(new ApiError('not found', 404))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('keeps retrying while the grace window is open, then stops polling for good', async () => {
            await expectLogic(logic, () => {
                logic.actions.check()
            })
                .toDispatchActions(['setLastError'])
                .toNotHaveDispatchedActions(['markRouteUnavailable'])

            jest.advanceTimersByTime(UNAVAILABLE_ROUTE_GRACE_MS - 1_000)
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toNotHaveDispatchedActions(['markRouteUnavailable'])
            expect(logic.values.permanentlyDisabled).toBe(false)

            jest.advanceTimersByTime(2_000)
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toDispatchActions(['markRouteUnavailable'])

            const callsAfterStop = mockLatestRetrieve.mock.calls.length
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toDispatchActions(['check'])
            expect(mockLatestRetrieve.mock.calls.length).toBe(callsAfterStop)
        })

        // An unserved poll route says nothing about a run the stream is already reporting. Dropping
        // the session with the poll would take the widget away mid-install, for the rest of the
        // tab — in exactly the rollout window the grace window exists to ride out.
        it('leaves a live run streaming when the grace window closes', async () => {
            logic.actions.markActive('posthog-integration')

            await expectLogic(logic, () => {
                logic.actions.check()
            }).toDispatchActions(['pollFailed'])
            jest.advanceTimersByTime(UNAVAILABLE_ROUTE_GRACE_MS)
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toDispatchActions(['markRouteUnavailable'])

            expect(logic.values.permanentlyDisabled).toBe(true)
            expect(logic.values.hasActiveSession).toBe(true)
            expect(logic.values.shouldStream).toBe(true)
        })

        it('reopens the window once a poll in between answers', async () => {
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toDispatchActions(['pollFailed'])

            jest.advanceTimersByTime(UNAVAILABLE_ROUTE_GRACE_MS - 1_000)
            mockLatestRetrieve.mockResolvedValue(null)
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toDispatchActions(['markInactive'])

            mockLatestRetrieve.mockRejectedValue(new ApiError('not found', 404))
            jest.advanceTimersByTime(2_000)
            await expectLogic(logic, () => {
                logic.actions.check()
            }).toNotHaveDispatchedActions(['markRouteUnavailable'])
            expect(logic.values.permanentlyDisabled).toBe(false)
        })
    })

    // Every project-id change asks for a poll, and nothing upstream limits how fast the id can
    // move — so an id that flaps turned into one request per change.
    describe('project-change polling', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('collapses a flapping project id into one poll', () => {
            mockLatestRetrieve.mockResolvedValue(null)

            projectLogic.actions.loadCurrentProjectSuccess({ id: 1 } as ProjectType)
            projectLogic.actions.loadCurrentProjectSuccess({ id: 2 } as ProjectType)
            projectLogic.actions.loadCurrentProjectSuccess({ id: 3 } as ProjectType)
            expect(mockLatestRetrieve).not.toHaveBeenCalled()

            jest.advanceTimersByTime(5_000)
            expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)
        })
    })

    // A poll asks for the project id it captured at the start. The poll after a project change is
    // delayed, so it cannot invalidate a request that is already in flight for the old project —
    // whose answer would otherwise decide the state of the project the user is now on.
    it('drops a poll that settles after the project id moved on', async () => {
        projectLogic.actions.loadCurrentProjectSuccess({ id: 1 } as ProjectType)

        let settleFirstPoll: (session: WizardSessionDTOApi | null) => void = () => {}
        mockLatestRetrieve.mockImplementation(
            () =>
                new Promise<WizardSessionDTOApi | null>((resolve) => {
                    settleFirstPoll = resolve
                })
        )

        await expectLogic(logic, () => {
            logic.actions.check()
        }).toDispatchActions(['check'])

        projectLogic.actions.loadCurrentProjectSuccess({ id: 2 } as ProjectType)

        await expectLogic(logic, () => {
            settleFirstPoll(makeSession({ run_phase: 'running' }))
        }).toFinishAllListeners()

        expect(logic.values.hasActiveSession).toBe(false)
    })

    // With two programs watched, a failure on the live one plus an empty answer from the other is
    // indistinguishable from "no run" unless the error is taken into account — and acting on it
    // would tear down a run that is still going.
    it('does not tear down a live run when one watched program fails and the other returns empty', async () => {
        logic.actions.watchWorkflow('self-driving')
        mockLatestRetrieve.mockResolvedValue(makeSession({ run_phase: 'running' }))
        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['markActive'])
            .toMatchValues({ hasActiveSession: true })

        mockLatestRetrieve.mockImplementation(async (_projectId: string, params: { workflow_id: string }) => {
            if (params.workflow_id === 'self-driving') {
                throw new ApiError('boom', 500)
            }
            return null
        })

        await expectLogic(logic, () => {
            logic.actions.check()
        })
            .toDispatchActions(['pollFailed'])
            .toNotHaveDispatchedActions(['markInactive', 'scheduleMarkInactive'])
            .toMatchValues({ hasActiveSession: true })
    })

    describe('hasResolvedSessionState', () => {
        it('starts unresolved and resolves on a settled poll, in either direction', async () => {
            expect(logic.values.hasResolvedSessionState).toBe(false)

            mockLatestRetrieve.mockResolvedValue(null)
            await expectLogic(logic, () => {
                logic.actions.check()
            })
                .toDispatchActions(['markInactive'])
                .toMatchValues({ hasResolvedSessionState: true })
        })

        // Without this, an access-denied user would leave every consumer waiting on a verdict that
        // can never arrive (the inbox takeover would never show).
        it('resolves on a permanent access denial', async () => {
            mockLatestRetrieve.mockRejectedValue(new ApiError('unauthorized', 401))
            await expectLogic(logic, () => {
                logic.actions.check()
            })
                .toDispatchActions(['markPermanentlyDisabled'])
                .toMatchValues({ hasResolvedSessionState: true, hasActiveSession: false })
        })

        // The regression this guards: markInactive doubling as the project-switch reset, which
        // stamped the new project "resolved, not running" before its first poll answered.
        it('goes back to unresolved on resetSessionState', () => {
            logic.actions.markActive('self-driving')
            expect(logic.values.hasResolvedSessionState).toBe(true)

            logic.actions.resetSessionState()
            expect(logic.values.hasResolvedSessionState).toBe(false)
            expect(logic.values.activeWorkflowId).toBeNull()
        })
    })

    describe('workflow watch refcounting', () => {
        it('keeps watching while any registration is open, stops after the last', () => {
            logic.actions.watchWorkflow('self-driving')
            logic.actions.watchWorkflow('self-driving')
            expect(logic.values.watchedWorkflows).toContain('self-driving')

            logic.actions.unwatchWorkflow('self-driving')
            expect(logic.values.watchedWorkflows).toContain('self-driving')

            logic.actions.unwatchWorkflow('self-driving')
            expect(logic.values.watchedWorkflows).not.toContain('self-driving')
        })

        // An unbalanced release must not poison the next registration (a negative count would make
        // one watchWorkflow insufficient to start watching again).
        it('an extra unwatch does not drive the count negative', () => {
            logic.actions.unwatchWorkflow('self-driving')
            logic.actions.watchWorkflow('self-driving')
            expect(logic.values.watchedWorkflows).toContain('self-driving')
        })
    })

    it('defers teardown (scheduleMarkInactive) when an active session goes terminal', async () => {
        logic.actions.markActive('posthog-integration')
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

    // The grace window is the anti-INC-886 mechanism: a terminal/empty poll schedules
    // teardown rather than ripping the stream down immediately, and a fresh active
    // signal inside the window cancels it. These assert the timer actually fires,
    // gets cancelled, and isn't pushed out by repeat schedules.
    describe('grace-window teardown', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('fires markInactive once the 30s grace window elapses', async () => {
            logic.actions.markActive('posthog-integration')
            logic.actions.scheduleMarkInactive()

            // Just before the deadline: the stream is still up.
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(29_000)
            }).toMatchValues({ hasActiveSession: true })

            // Crossing the 30s deadline tears it down.
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(2_000)
            })
                .toDispatchActions(['markInactive'])
                .toMatchValues({ hasActiveSession: false, shouldStream: false })
        })

        it('cancels the pending teardown when markActive fires inside the window', async () => {
            logic.actions.markActive('posthog-integration')
            logic.actions.scheduleMarkInactive()

            jest.advanceTimersByTime(15_000)
            // A fresh active signal (e.g. an SSE heartbeat) cancels the scheduled teardown.
            logic.actions.markActive('posthog-integration')

            await expectLogic(logic, () => {
                jest.advanceTimersByTime(60_000)
            })
                .toNotHaveDispatchedActions(['markInactive'])
                .toMatchValues({ hasActiveSession: true, shouldStream: true })
        })

        it('keeps the original deadline when scheduleMarkInactive is repeated (idempotent)', async () => {
            logic.actions.markActive('posthog-integration')
            logic.actions.scheduleMarkInactive() // deadline = now + 30s

            jest.advanceTimersByTime(20_000)
            logic.actions.scheduleMarkInactive() // must NOT push the deadline out to now + 30s

            // 10s more reaches the *original* 30s deadline → teardown fires. If the repeat
            // had reset the clock, markInactive wouldn't fire until 30s from the repeat.
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(10_000)
            })
                .toDispatchActions(['markInactive'])
                .toMatchValues({ hasActiveSession: false })
        })
    })
})
