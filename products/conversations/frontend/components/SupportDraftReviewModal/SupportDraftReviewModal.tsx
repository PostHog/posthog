import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'

import { myTicketsSceneLogic } from '../../scenes/myTickets/myTicketsSceneLogic'

export function SupportDraftReviewModal(): JSX.Element {
    const { isReviewingDraft } = useValues(myTicketsSceneLogic)
    const { closeDraftReview } = useActions(myTicketsSceneLogic)
    const { isSendSupportRequestSubmitting } = useValues(supportLogic)

    return (
        <LemonModal
            isOpen={isReviewingDraft}
            onClose={closeDraftReview}
            title="Review your support ticket"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeDraftReview}>
                        Not now
                    </LemonButton>
                    <LemonButton
                        form="support-modal-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="support-draft-send"
                        loading={isSendSupportRequestSubmitting}
                    >
                        Send to PostHog support
                    </LemonButton>
                </div>
            }
        >
            <SupportForm />
        </LemonModal>
    )
}
