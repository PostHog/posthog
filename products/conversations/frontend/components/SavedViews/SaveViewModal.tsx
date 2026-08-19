import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FiltersSummary } from './FiltersSummary'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

export function SaveViewModal({ id }: TicketViewsLogicProps): JSX.Element {
    const { isSaveModalOpen, viewName, currentFilters } = useValues(ticketViewsLogic({ id }))
    const { closeSaveModal, setViewName, saveView } = useActions(ticketViewsLogic({ id }))
    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined

    return (
        <LemonModal
            isOpen={isSaveModalOpen}
            onClose={closeSaveModal}
            title="Save current view"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSaveModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveView}
                        disabledReason={editDisabledReason ?? (!viewName.trim() ? 'Enter a name' : undefined)}
                    >
                        Save view
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <LemonInput
                    placeholder="View name"
                    value={viewName}
                    onChange={setViewName}
                    autoFocus
                    disabledReason={editDisabledReason}
                    onPressEnter={editDisabledReason ? undefined : saveView}
                />
                <FiltersSummary filters={currentFilters} />
            </div>
        </LemonModal>
    )
}
