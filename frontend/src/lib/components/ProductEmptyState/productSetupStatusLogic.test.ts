import { expectLogic } from 'kea-test-utils'

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
    // empty state or (worse) permanently hides it for users who never skipped.
    it('skip hides the empty state without touching detection, and unskip restores it', async () => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus('needs-setup')
        expect(logic.values.showEmptyState).toBe(true)

        await expectLogic(logic, () => logic.actions.skipEmptyState()).toFinishAllListeners()
        expect(logic.values.skipped).toBe(true)
        expect(logic.values.showEmptyState).toBe(false)
        // Detection is untouched by skipping.
        expect(logic.values.status).toBe('needs-setup')

        await expectLogic(logic, () => logic.actions.unskipEmptyState()).toFinishAllListeners()
        expect(logic.values.showEmptyState).toBe(true)
    })

    it.each([
        ['loading', false],
        ['needs-setup', true],
        ['waiting-for-data', true],
        ['has-data', false],
    ] as const)('status %s → showEmptyState %s', (status, expected) => {
        const logic = mountLogic()
        logic.actions.setDetectedStatus(status)
        expect(logic.values.showEmptyState).toBe(expected)
    })
})
