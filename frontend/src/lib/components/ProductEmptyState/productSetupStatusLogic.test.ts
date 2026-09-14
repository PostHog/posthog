import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { SETUP_STATUS_FAIL_OPEN_MS, productSetupStatusLogic } from './productSetupStatusLogic'

// Mutate `document.hidden` and then fire the event, so the kea disposables plugin pauses and
// resumes the clock exactly as it does in the browser.
const setHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (hidden ? 'hidden' : 'visible'),
    })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('productSetupStatusLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockClear()
    })

    function mountLogic(): ReturnType<typeof productSetupStatusLogic.build> {
        const logic = productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS })
        logic.mount()
        return logic
    }

    it('keeps setup attribution across route changes and reports data only once', () => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus('needs-setup')
        logic.actions.reportSetupShown('needs-setup')
        logic.actions.reportSetupInteraction('wizard command copied', 'needs-setup', 'wizard')
        logic.actions.reportSetupInteraction('agent prompt copied', 'needs-setup', 'agent')

        expect(posthog.capture).toHaveBeenLastCalledWith(
            'product empty state agent prompt copied',
            expect.objectContaining({
                setup_attempt_id: expect.any(String),
                initial_setup_route: 'wizard',
                setup_route: 'agent',
            })
        )
        const attemptId = logic.values.setupAttempt?.id
        logic.actions.setDetectedStatus('has-data')
        logic.actions.setDetectedStatus('has-data')
        const detected = jest
            .mocked(posthog.capture)
            .mock.calls.filter(([event]) => event === 'product empty state data detected')
        expect(detected).toHaveLength(1)
        expect(detected[0][1]).toMatchObject({
            setup_attempt_id: attemptId,
            initial_setup_route: 'wizard',
            setup_route: 'agent',
        })
    })

    it('does not count forced previews or existing data as setup', () => {
        const logic = mountLogic()
        logic.actions.reportSetupShown('needs-setup', true)
        logic.actions.reportSetupInteraction('agent prompt copied', 'needs-setup', 'agent', true)
        logic.actions.setDetectedStatus('has-data')
        expect(logic.values.setupAttempt).toBeNull()
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it('keeps the same attempt after remounting setup', () => {
        const logic = productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS })
        const unmount = logic.mount()
        logic.actions.reportSetupShown('needs-setup')
        logic.actions.reportSetupInteraction('manual setup clicked', 'needs-setup', 'manual')
        const attemptId = logic.values.setupAttempt?.id
        unmount()

        const remounted = mountLogic()
        remounted.actions.reportSetupShown('needs-setup')
        expect(remounted.values.setupAttempt).toMatchObject({ id: attemptId, initialRoute: 'manual' })
    })

    it('does not attribute data from a project with the same numeric ID to the current setup attempt', () => {
        const logic = mountLogic()
        logic.actions.reportSetupShown('needs-setup')
        const otherTeam = { ...teamLogic.values.currentTeam!, uuid: '00000000-0000-4000-8000-000000000123' }
        teamLogic.actions.loadCurrentTeamSuccess(otherTeam)
        logic.actions.setDetectedStatus('has-data')
        expect(logic.values.setupAttempt).toBeNull()
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'product empty state data detected')
        ).toHaveLength(0)
    })

    // Guards the skip path end to end: a broken skip either traps users on the
    // empty state or (worse) permanently hides it for users who never skipped. The gate
    // decides from `skipped` and `status` together, so both have to move independently.
    it('skip flips only skipped, leaving detection alone, and unskip restores it', async () => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus('needs-setup')
        expect(logic.values.skipped).toBe(false)

        await expectLogic(logic, () => logic.actions.skipEmptyState()).toFinishAllListeners()
        expect(logic.values.skipped).toBe(true)
        // Detection is untouched by skipping.
        expect(logic.values.status).toBe('needs-setup')

        await expectLogic(logic, () => logic.actions.unskipEmptyState()).toFinishAllListeners()
        expect(logic.values.skipped).toBe(false)
        expect(logic.values.status).toBe('needs-setup')
    })

    // `mode` picks which copy and preview state the empty state renders.
    it.each([
        ['loading', 'needs-setup'],
        ['unknown', 'needs-setup'],
        ['needs-setup', 'needs-setup'],
        ['waiting-for-data', 'waiting-for-data'],
        ['has-data', 'needs-setup'],
    ] as const)('status %s → mode %s', (status, expected) => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus(status)
        expect(logic.values.mode).toBe(expected)
    })

    // Guards the no-downgrade rule. Products that poll re-answer while the scene is mounted,
    // so without it a failed first check (which fails open to the live scene) followed by a
    // successful zero-count poll replaces that scene with the setup screen 20 seconds later.
    it.each([
        ['unknown', 'unknown'],
        ['has-data', 'has-data'],
        // A user-initiated transition, e.g. support switched off with no tickets, still lands.
        ['waiting-for-data', 'needs-setup'],
    ] as const)('a later needs-setup over %s settles on %s', (settled, expected) => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus(settled)
        logic.actions.setDetectedStatus('needs-setup')
        expect(logic.values.status).toBe(expected)
    })

    // Guards the team stamp: without it, a project switch serves the previous
    // team's detected status and the gate exposes (or hides) the wrong screen.
    it('a detected status does not survive a project switch', async () => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus('has-data')
        expect(logic.values.status).toBe('has-data')

        const otherTeam = { ...teamLogic.values.currentTeam!, id: (teamLogic.values.currentTeamId ?? 0) + 1 }
        await expectLogic(logic, () => teamLogic.actions.loadCurrentTeamSuccess(otherTeam)).toFinishAllListeners()
        expect(logic.values.status).toBe('loading')
    })

    // Without the clock, a detection that never answers (or an answer stamped for a team the
    // user has left) holds `loading` for the whole session, and the gate keeps the scene
    // behind a spinner with no timeout, retry, or escape.
    it('fails open once loading runs out of time', () => {
        jest.useFakeTimers()
        try {
            const logic = mountLogic()
            expect(logic.values.status).toBe('loading')

            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS)
            expect(logic.values.status).toBe('unknown')
            expect(posthog.capture).toHaveBeenCalledWith(
                'product empty state detection timed out',
                expect.objectContaining({ product_key: ProductKey.MCP_ANALYTICS })
            )

            // A late answer still counts, so the surface settles on the real verdict.
            logic.actions.setDetectedStatus('waiting-for-data')
            expect(logic.values.status).toBe('waiting-for-data')
        } finally {
            jest.useRealTimers()
        }
    })

    // The team reloads itself every 30 seconds. Re-arming on each reload would push the
    // deadline past every tick, so the spinner would never give way.
    it('keeps the clock running across a plain team reload', () => {
        jest.useFakeTimers()
        try {
            const logic = mountLogic()
            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS / 2)
            teamLogic.actions.loadCurrentTeamSuccess(teamLogic.values.currentTeam!)
            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS / 2)

            expect(logic.values.status).toBe('unknown')
        } finally {
            jest.useRealTimers()
        }
    })

    // The plugin tears the timer down when the tab hides and runs the setup again when it
    // returns. Switching tabs is the normal response to a slow screen, so a fresh deadline on
    // each return would hold the spinner for the whole session.
    it('counts visible time in total, so a tab switch cannot postpone the fail-open', () => {
        jest.useFakeTimers()
        try {
            const logic = mountLogic()
            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS / 2)

            setHidden(true)
            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS * 2)
            // Hidden time does not count, so the clock still owes the other half.
            expect(logic.values.status).toBe('loading')

            setHidden(false)
            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS / 2)
            expect(logic.values.status).toBe('unknown')
        } finally {
            setHidden(false)
            jest.useRealTimers()
        }
    })

    it('restarts the clock for the team the user switched to', () => {
        jest.useFakeTimers()
        try {
            const logic = mountLogic()
            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS)
            expect(logic.values.status).toBe('unknown')

            const otherTeam = { ...teamLogic.values.currentTeam!, id: (teamLogic.values.currentTeamId ?? 0) + 1 }
            teamLogic.actions.loadCurrentTeamSuccess(otherTeam)
            expect(logic.values.status).toBe('loading')

            jest.advanceTimersByTime(SETUP_STATUS_FAIL_OPEN_MS)
            expect(logic.values.status).toBe('unknown')
        } finally {
            jest.useRealTimers()
        }
    })
})
