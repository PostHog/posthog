import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

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

        expect(screen.getByRole('button', { name: /Restore 2/ })).toBeInTheDocument()
    })

    it('lists only the flags still deleted after a restore that partly failed', () => {
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })
        logic.actions.bulkRestoreFlagsFinished({
            restoredIds: [1],
            failed: [{ id: 2, key: 'flag-2', errorMessage: 'Restoring is not available for this flag yet.' }],
        })
        renderModal()

        expect(screen.getByText('Restored 1 flag')).toBeInTheDocument()
        expect(screen.getByText('Failed to restore 1 flag')).toBeInTheDocument()
        expect(screen.getByText('Deleted 1 flag')).toBeInTheDocument()
        expect(screen.queryByText('flag-1')).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /Restore \d/ })).not.toBeInTheDocument()
    })
})
