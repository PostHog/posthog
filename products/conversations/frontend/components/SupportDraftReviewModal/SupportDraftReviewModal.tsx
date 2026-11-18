import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { myTicketsSceneLogic } from '../../scenes/myTickets/myTicketsSceneLogic'

export function SupportDraftReviewModal(): JSX.Element {
    const { isReviewingDraft, draftReviewState } = useValues(myTicketsSceneLogic)
    const { closeDraftReview } = useActions(myTicketsSceneLogic)
    const { isSendSupportRequestSubmitting, sendSupportRequest } = useValues(supportLogic)

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
                    {draftReviewState === 'ready' && (
                        <LemonButton
                            form="support-modal-form"
                            htmlType="submit"
                            type="primary"
                            data-attr="support-draft-send"
                            loading={isSendSupportRequestSubmitting}
                        >
                            Send to PostHog support
                        </LemonButton>
                    )}
                </div>
            }
        >
            {draftReviewState === 'checking_plan' ? (
                <div className="flex justify-center p-4">
                    <Spinner />
                </div>
            ) : draftReviewState === 'not_entitled' ? (
                <div className="flex flex-col gap-4">
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Ask the community',
                            to: 'https://posthog.com/questions',
                            targetBlank: true,
                        }}
                    >
                        Your plan doesn't include support tickets. You can ask the community instead, or upgrade to
                        message our support engineers.
                    </LemonBanner>
                    <LemonMarkdown className="border rounded p-3">{sendSupportRequest.message ?? ''}</LemonMarkdown>
                </div>
            ) : (
                <SupportForm />
            )}
        </LemonModal>
    )
}
