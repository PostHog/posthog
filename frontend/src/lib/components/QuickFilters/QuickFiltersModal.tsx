import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { QuickFilterForm } from './QuickFilterForm'
import { QuickFiltersLogicProps } from './quickFiltersLogic'
import { QuickFiltersModalContent } from './QuickFiltersModalContent'
import { quickFiltersModalLogic } from './quickFiltersModalLogic'

export function QuickFiltersModal({ context }: QuickFiltersLogicProps): JSX.Element {
    const { isModalOpen, view, modalTitle } = useValues(quickFiltersModalLogic({ context }))
    const { closeModal } = useActions(quickFiltersModalLogic({ context }))

    return (
        <LemonModal title={modalTitle} isOpen={isModalOpen} onClose={closeModal} width={800}>
            {view === 'list' ? <QuickFiltersModalContent context={context} /> : <QuickFilterForm context={context} />}
        </LemonModal>
    )
}
