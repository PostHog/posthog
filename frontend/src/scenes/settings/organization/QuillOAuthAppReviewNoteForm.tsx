import { useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'

import { Button, Field, FieldDescription, FieldError, FieldLabel, Textarea } from '@posthog/quill'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { REVIEW_NOTE_SUBMIT_LABELS } from './oauthAppProvisioningStatus'
import { REVIEW_NOTE_MAX_LENGTH, oauthAppReviewNoteLogic } from './oauthAppReviewNoteLogic'

export function QuillOAuthAppReviewNoteForm({ app }: { app: OrganizationOAuthApplicationApi }): JSX.Element {
    const { isReviewNoteSubmitting } = useValues(oauthAppReviewNoteLogic({ appId: app.id }))

    return (
        <Form
            logic={oauthAppReviewNoteLogic}
            props={{ appId: app.id }}
            formKey="reviewNote"
            enableFormOnSubmit
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
                <Button
                    type="submit"
                    variant="primary"
                    loading={isReviewNoteSubmitting}
                    data-attr="oauth-app-review-note-submit"
                >
                    {REVIEW_NOTE_SUBMIT_LABELS[app.provisioning_status] ?? 'Send note'}
                </Button>
            </div>
        </Form>
    )
}
