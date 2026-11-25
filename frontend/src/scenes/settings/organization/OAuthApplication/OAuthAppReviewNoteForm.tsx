import { useActions } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { REVIEW_NOTE_MAX_LENGTH, oauthAppReviewNoteLogic } from './oauthAppReviewNoteLogic'
import { OAuthAppReviewNotePreview } from './OAuthAppReviewNotePreview'

export function OAuthAppReviewNoteForm({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { openNotePreview } = useActions(oauthAppReviewNoteLogic({ appId: app.id }))

    return (
        <Form logic={oauthAppReviewNoteLogic} props={{ appId: app.id }} formKey="reviewNote">
            <div className="flex flex-col gap-2">
                <LemonField
                    name="note"
                    label="Note to PostHog staff"
                    help="What the application does, why it creates accounts or provisions resources, and what changed since the last decision."
                >
                    <LemonTextArea maxLength={REVIEW_NOTE_MAX_LENGTH} minRows={4} data-attr="oauth-app-review-note" />
                </LemonField>
                <div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={openNotePreview}
                        data-attr="oauth-app-review-note-preview"
                    >
                        Review before sending
                    </LemonButton>
                </div>
            </div>
            <OAuthAppReviewNotePreview app={app} />
        </Form>
    )
}
