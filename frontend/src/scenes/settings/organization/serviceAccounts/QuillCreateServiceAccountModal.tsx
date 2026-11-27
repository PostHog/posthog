import { useActions, useValues } from 'kea'
import { Field as KeaField, Form } from 'kea-forms'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Text,
} from '@posthog/quill'

import { ServiceAccountsLogicProps, serviceAccountsLogic } from './serviceAccountsLogic'

export function QuillCreateServiceAccountModal(props: ServiceAccountsLogicProps): JSX.Element {
    const logic = serviceAccountsLogic(props)
    const { creating, isNewAccountSubmitting, createFailed } = useValues(logic)
    const { setCreating, submitNewAccount } = useActions(logic)

    return (
        <Dialog open={creating} onOpenChange={(open) => !isNewAccountSubmitting && setCreating(open)}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Create service account</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Form
                        logic={serviceAccountsLogic}
                        props={props}
                        formKey="newAccount"
                        enableFormOnSubmit
                        className="flex flex-col gap-4"
                    >
                        <Text size="xs">
                            Give an integration or automation its own identity. The account uses your organization's
                            default project access.
                        </Text>
                        <KeaField name="name" noStyle>
                            {({ value, onChange, error }) => (
                                <Field data-invalid={!!error}>
                                    <FieldLabel htmlFor="service-account-name">Name</FieldLabel>
                                    <Input
                                        id="service-account-name"
                                        autoFocus
                                        maxLength={150}
                                        value={value}
                                        onChange={(event) => onChange(event.target.value)}
                                        disabled={isNewAccountSubmitting}
                                        placeholder="e.g. Release automation"
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                        {createFailed && (
                            <Text size="xs" role="alert">
                                Couldn't create the service account. Check the name and try again.
                            </Text>
                        )}
                    </Form>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setCreating(false)} disabled={isNewAccountSubmitting}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitNewAccount}
                        loading={isNewAccountSubmitting}
                        data-attr="service-account-create-submit"
                    >
                        Create service account
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
