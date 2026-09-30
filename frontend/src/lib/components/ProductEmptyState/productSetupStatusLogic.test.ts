import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productSetupStatusLogic } from './productSetupStatusLogic'

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
})
