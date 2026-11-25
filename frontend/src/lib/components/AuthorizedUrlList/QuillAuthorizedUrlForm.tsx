import { Form, Field as KeaField } from 'kea-forms'

import { Button, Field, FieldError, Input } from '@posthog/quill'

import { AuthorizedUrlListLogicProps, authorizedUrlListLogic } from './authorizedUrlListLogic'

export function QuillAuthorizedUrlForm({
    logicProps,
    placeholder,
    submitting,
    onCancel,
}: {
    logicProps: AuthorizedUrlListLogicProps
    placeholder: string
    submitting: boolean
    onCancel: () => void
}): JSX.Element {
    return (
        <Form
            logic={authorizedUrlListLogic}
            props={logicProps}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="flex w-full flex-col gap-2"
        >
            <KeaField name="url" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <Input
                            id={id}
                            autoFocus
                            value={value ?? ''}
                            onChange={(event) => onChange(event.target.value)}
                            aria-invalid={!!error}
                            placeholder={placeholder}
                            data-attr="url-input"
                        />
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" onClick={onCancel}>
                    Cancel
                </Button>
                <Button type="submit" variant="primary" loading={submitting} data-attr="url-save">
                    Save
                </Button>
            </div>
        </Form>
    )
}
