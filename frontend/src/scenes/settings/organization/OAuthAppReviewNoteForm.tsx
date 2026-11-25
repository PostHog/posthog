import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { REVIEW_NOTE_SUBMIT_LABELS } from './oauthAppProvisioningStatus'
import { REVIEW_NOTE_MAX_LENGTH, oauthAppReviewNoteLogic } from './oauthAppReviewNoteLogic'

export function OAuthAppReviewNoteForm({ app }: { app: OrganizationOAuthApplicationApi }): JSX.Element {
    const { isReviewNoteSubmitting } = useValues(oauthAppReviewNoteLogic({ appId: app.id }))

    return (
        <Form logic={oauthAppReviewNoteLogic} props={{ appId: app.id }} formKey="reviewNote" enableFormOnSubmit>
            <div className="flex flex-col gap-2">
                <LemonField
                    name="note"
                    label="Note to PostHog staff"
                    help="What the application does, why it creates accounts or provisions resources, and what changed since the last decision."
                >
                    <LemonTextArea maxLength={REVIEW_NOTE_MAX_LENGTH} minRows={3} data-attr="oauth-app-review-note" />
                </LemonField>
                <div>
                    <LemonButton
                        type="primary"
                        size="small"
                        htmlType="submit"
                        loading={isReviewNoteSubmitting}
                        data-attr="oauth-app-review-note-submit"
                    >
                        {REVIEW_NOTE_SUBMIT_LABELS[app.provisioning_status] ?? 'Send note'}
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
