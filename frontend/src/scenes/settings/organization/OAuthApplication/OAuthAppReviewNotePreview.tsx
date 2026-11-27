import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { REVIEW_NOTE_SUBMIT_LABELS } from '../oauthAppProvisioningStatus'
import { oauthAppReviewNoteLogic } from './oauthAppReviewNoteLogic'

export function OAuthAppReviewNotePreview({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const logic = oauthAppReviewNoteLogic({ appId: app.id })
    const { isNotePreviewOpen, reviewNote, isReviewNoteSubmitting } = useValues(logic)
    const { closeNotePreview, submitReviewNote } = useActions(logic)

    return (
        <LemonModal
            isOpen={isNotePreviewOpen}
            onClose={closeNotePreview}
            title="Review your note"
            description="PostHog staff read your note in the review of this application, next to what PostHog read from your metadata document."
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeNotePreview}
                        disabledReason={isReviewNoteSubmitting ? 'Sending' : undefined}
                    >
                        Keep editing
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitReviewNote}
                        loading={isReviewNoteSubmitting}
                        data-attr="oauth-app-review-note-submit"
                    >
                        {REVIEW_NOTE_SUBMIT_LABELS[app.provisioning_status] ?? 'Send note'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <div>
                    <div className="text-xs font-semibold text-secondary mb-1">Your note</div>
                    <p className="m-0 whitespace-pre-wrap border rounded p-3 bg-surface-secondary">{reviewNote.note}</p>
                </div>
                <div>
                    <div className="text-xs font-semibold text-secondary mb-1">Sent with it</div>
                    <ul className="m-0 pl-5 list-disc">
                        <li>The application's client ID: {app.client_id}</li>
                        <li>Your email, so staff know who answered</li>
                        <li>The review's history and your metadata document, which staff already have</li>
                    </ul>
                </div>
            </div>
        </LemonModal>
    )
}
