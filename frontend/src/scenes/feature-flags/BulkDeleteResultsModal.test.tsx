import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'

import { BulkDeleteResultsModal } from './BulkDeleteResultsModal'
import { DeletedFlagInfo, flagSelectionLogic } from './flagSelectionLogic'

const deletedFlag = (id: number): DeletedFlagInfo => ({
    id,
    key: `flag-${id}`,
    rollout_state: 'partial',
    active_variant: null,
})

describe('BulkDeleteResultsModal', () => {
    let logic: ReturnType<typeof flagSelectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = flagSelectionLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    function renderModal(): void {
        render(
            <Provider>
                <BulkDeleteResultsModal />
            </Provider>
        )
    }

    it('offers to restore every deleted flag', () => {
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })
        renderModal()

        expect(getByDataAttr(document.body, 'bulk-restore-deleted-flags')).toHaveTextContent('Restore 2 flags')
    })

    it('lists only the flags still deleted after a restore that partly failed, and offers to retry them', () => {
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })
        logic.actions.bulkRestoreFlagSucceeded(1)
        logic.actions.bulkRestoreFlagsFinished({
            restoredIds: [1],
            failed: [{ id: 2, key: 'flag-2', errorMessage: 'Restoring is not available for this flag yet.' }],
        })
        renderModal()

        expect(screen.getByText('Restored 1 flag')).toBeInTheDocument()
        expect(screen.getByText('Failed to restore 1 flag')).toBeInTheDocument()
        expect(screen.getByText('Deleted 1 flag')).toBeInTheDocument()
        expect(screen.queryByText('flag-1')).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('Clean up code references with AI'))
        const cleanupPrompt = screen.getByText(/Find and remove all references/).textContent
        expect(cleanupPrompt).toContain('- flag-2')
        expect(cleanupPrompt).not.toContain('flag-1')

        expect(getByDataAttr(document.body, 'bulk-restore-deleted-flags')).toHaveTextContent('Restore 1 flag')
    })

    it('stays open until the restore finishes', async () => {
        useMocks({
            get: {
                '/api/projects/:team/feature_flags/': { count: 0, results: [] },
            },
            patch: {
                '/api/projects/:team/feature_flags/:id/': () => [500, { detail: 'Server error' }],
            },
        })
        logic.actions.showResultsModal({ deleted: [deletedFlag(1)], errors: [] })
        renderModal()

        fireEvent.click(getByDataAttr(document.body, 'bulk-restore-deleted-flags'))
        expect(screen.queryByLabelText('close')).not.toBeInTheDocument()
        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape', keyCode: 27 })
        expect(logic.values.resultsModalVisible).toBe(true)

        // Once the restore fails, the results list it and close again.
        await act(async () => {
            await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])
        })
        expect(screen.getByText('Failed to restore 1 flag')).toBeInTheDocument()
        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape', keyCode: 27 })
        expect(logic.values.resultsModalVisible).toBe(false)
    })
})
