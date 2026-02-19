import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SessionAnalysisSetup } from './SessionAnalysisSetup'
import { SourcesList } from './SourcesList'
import { inboxSceneLogic } from './inboxSceneLogic'

export function SourcesModal(): JSX.Element {
    const { sourcesModalOpen, sessionAnalysisSetupOpen } = useValues(inboxSceneLogic)
    const { closeSourcesModal, closeSessionAnalysisSetup } = useActions(inboxSceneLogic)

    return (
        <LemonModal
            isOpen={sourcesModalOpen}
            onClose={closeSourcesModal}
            simple
            width={sessionAnalysisSetupOpen ? '48rem' : '32rem'}
        >
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    {sessionAnalysisSetupOpen && (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={closeSessionAnalysisSetup}
                        />
                    )}
                    <h3 className="font-semibold mb-0">
                        {sessionAnalysisSetupOpen ? 'Session analysis filters' : 'Signal sources'}
                    </h3>
                </div>
                {!sessionAnalysisSetupOpen && (
                    <p className="text-xs text-secondary mt-1 mb-0">Set up sources feeding the Inbox.</p>
                )}
            </LemonModal.Header>
            <LemonModal.Content className={sessionAnalysisSetupOpen ? 'p-0 rounded-b' : ''}>
                {sessionAnalysisSetupOpen ? <SessionAnalysisSetup /> : <SourcesList />}
            </LemonModal.Content>
        </LemonModal>
    )
}
