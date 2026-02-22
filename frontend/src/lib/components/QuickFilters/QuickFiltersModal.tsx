import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { QuickFilterForm } from './QuickFilterForm'
import { QuickFiltersModalContent } from './QuickFiltersModalContent'
import { ModalView, QuickFiltersModalLogicProps, quickFiltersModalLogic } from './quickFiltersModalLogic'

export function QuickFiltersModal({ context, modalKey, onNewFilterCreated }: QuickFiltersModalLogicProps): JSX.Element {
    const logicProps = { context, modalKey, onNewFilterCreated }
    const { isModalOpen, view, modalTitle } = useValues(quickFiltersModalLogic(logicProps))
    const { closeModal } = useActions(quickFiltersModalLogic(logicProps))

    return (
        <LemonModal title={modalTitle} isOpen={isModalOpen} onClose={closeModal} width={800}>
            {view === ModalView.List ? (
                <QuickFiltersModalContent context={context} modalKey={modalKey} />
            ) : (
                <QuickFilterForm context={context} modalKey={modalKey} />
            )}
        </LemonModal>
    )
}
