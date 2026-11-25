import { useActions } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'

import { Button, Field, FieldDescription, FieldError, FieldLabel, Textarea } from '@posthog/quill'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { REVIEW_NOTE_MAX_LENGTH, oauthAppReviewNoteLogic } from './oauthAppReviewNoteLogic'
import { QuillOAuthAppReviewNotePreview } from './QuillOAuthAppReviewNotePreview'

export function QuillOAuthAppReviewNoteForm({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const { openNotePreview } = useActions(oauthAppReviewNoteLogic({ appId: app.id }))

    return (
        <Form
            logic={oauthAppReviewNoteLogic}
            props={{ appId: app.id }}
            formKey="reviewNote"
            className="flex flex-col gap-2"
        >
            <KeaField name="note" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <FieldLabel htmlFor={id}>Note to PostHog staff</FieldLabel>
                        <Textarea
                            id={id}
                            value={value ?? ''}
                            onChange={(event) => onChange(event.target.value)}
                            maxLength={REVIEW_NOTE_MAX_LENGTH}
                            data-attr="oauth-app-review-note"
                        />
                        <FieldDescription>
                            What the application does, why it creates accounts or provisions resources, and what changed
                            since the last decision.
                        </FieldDescription>
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>
            <div>
                <Button variant="primary" onClick={openNotePreview} data-attr="oauth-app-review-note-preview">
                    Review before sending
                </Button>
            </div>
            <QuillOAuthAppReviewNotePreview app={app} />
        </Form>
    )
}
