import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productSetupStatusLogic } from './productSetupStatusLogic'

describe('productSetupStatusLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    function mountLogic(): ReturnType<typeof productSetupStatusLogic.build> {
        const logic = productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS })
        logic.mount()
        return logic
    }

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
