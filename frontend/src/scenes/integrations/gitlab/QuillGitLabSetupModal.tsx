import { Form, Field as KeaField } from 'kea-forms'

import { IconGitLab } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { GitLabSetupModalLogicProps, gitlabSetupModalLogic } from './gitlabSetupModalLogic'

export function QuillGitLabSetupModal({
    logicProps,
    submitting,
    onSubmit,
}: {
    logicProps: GitLabSetupModalLogicProps
    submitting: boolean
    onSubmit: () => void
}): JSX.Element {
    return (
        <Dialog
            open={logicProps.isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    logicProps.onComplete()
                }
            }}
        >
            <DialogContent>
                <Form logic={gitlabSetupModalLogic} props={logicProps} formKey="gitlabIntegration">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <IconGitLab />
                            Configure GitLab integration
                        </DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <div className="flex flex-col gap-4">
                            <KeaField name="hostname" noStyle>
                                {({ id, value, onChange, error }) => (
                                    <Field data-invalid={error ? true : undefined}>
                                        <FieldLabel htmlFor={id}>Hostname</FieldLabel>
                                        <Input
                                            id={id}
                                            type="text"
                                            placeholder="https://gitlab.com"
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                        />
                                        {error && <FieldError>{error}</FieldError>}
                                    </Field>
                                )}
                            </KeaField>

                            <KeaField name="projectId" noStyle>
                                {({ id, value, onChange, error }) => (
                                    <Field data-invalid={error ? true : undefined}>
                                        <FieldLabel htmlFor={id}>Project ID</FieldLabel>
                                        <Input
                                            id={id}
                                            type="text"
                                            placeholder="1234567"
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                        />
                                        {error && <FieldError>{error}</FieldError>}
                                        <FieldDescription>
                                            <Button
                                                variant="link"
                                                size="inline"
                                                nativeButton={false}
                                                render={
                                                    <LinkPrimitive
                                                        to="https://docs.gitlab.com/user/project/working_with_projects/#find-the-project-id"
                                                        target="_blank"
                                                    />
                                                }
                                            >
                                                Find your Project ID
                                            </Button>
                                        </FieldDescription>
                                    </Field>
                                )}
                            </KeaField>

                            <KeaField name="projectAccessToken" noStyle>
                                {({ id, value, onChange, error }) => (
                                    <Field data-invalid={error ? true : undefined}>
                                        <FieldLabel htmlFor={id}>Project access token</FieldLabel>
                                        <Input
                                            id={id}
                                            type="password"
                                            placeholder="xxxxx-x_xxxxxxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxx.xx.xxxxxxxxx"
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                        />
                                        {error && <FieldError>{error}</FieldError>}
                                        <FieldDescription>
                                            Learn how to{' '}
                                            <Button
                                                variant="link"
                                                size="inline"
                                                nativeButton={false}
                                                render={
                                                    <LinkPrimitive
                                                        to="https://docs.gitlab.com/user/project/settings/project_access_tokens"
                                                        target="_blank"
                                                    />
                                                }
                                            >
                                                create a project access token
                                            </Button>
                                        </FieldDescription>
                                    </Field>
                                )}
                            </KeaField>
                        </div>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="primary" type="submit" loading={submitting} onClick={onSubmit}>
                            Connect
                        </Button>
                    </DialogFooter>
                </Form>
            </DialogContent>
        </Dialog>
    )
}
