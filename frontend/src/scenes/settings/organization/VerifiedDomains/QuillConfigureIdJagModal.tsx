import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    FieldDescription,
    Input,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function QuillConfigureIdJagModal({
    idJagReady,
    onClose,
}: {
    idJagReady: boolean
    onClose: () => void
}): JSX.Element {
    const { configureIdJagModalId, configureIdJagModalLoading, isIdJagConfigSubmitting } =
        useValues(verifiedDomainsLogic)
    const { submitIdJagConfig } = useActions(verifiedDomainsLogic)

    return (
        <Dialog open={!!configureIdJagModalId} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>Configure XAA (ID-JAG)</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    {configureIdJagModalLoading ? (
                        <Skeleton className="h-40 w-full" />
                    ) : (
                        <Form
                            logic={verifiedDomainsLogic}
                            formKey="idJagConfig"
                            enableFormOnSubmit
                            className="flex flex-col gap-4"
                        >
                            <QuillSettingFormField name="id_jag_issuer_url" label="IdP issuer URL">
                                {({ id, value, onChange, invalid }) => (
                                    <>
                                        <Input
                                            id={id}
                                            className="ph-ignore-input"
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder="https://idp.example.com"
                                            autoComplete="off"
                                            aria-invalid={invalid || undefined}
                                        />
                                        <FieldDescription>
                                            The trusted identity provider issuer URL. Must match the iss claim on ID-JAG
                                            tokens for users on this domain.
                                        </FieldDescription>
                                    </>
                                )}
                            </QuillSettingFormField>
                            <QuillSettingFormField name="id_jag_jwks_url" label="JWKS URL (optional)">
                                {({ id, value, onChange, invalid }) => (
                                    <>
                                        <Input
                                            id={id}
                                            className="ph-ignore-input"
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder="https://idp.example.com/.well-known/jwks.json"
                                            autoComplete="off"
                                            aria-invalid={invalid || undefined}
                                        />
                                        <FieldDescription>
                                            Override JWKS discovery. Leave empty to use OIDC discovery at the issuer
                                            URL.
                                        </FieldDescription>
                                    </>
                                )}
                            </QuillSettingFormField>
                            <QuillSettingFormField name="id_jag_allowed_clients" label="Allowed client IDs (optional)">
                                {({ value, onChange }) => (
                                    <>
                                        <TagsCombobox
                                            value={value ?? []}
                                            onChange={onChange}
                                            placeholder="Add client IDs..."
                                            customValueNoun="client ID"
                                            className="w-full"
                                        />
                                        <FieldDescription>
                                            Restrict which client_id values are accepted. Leave empty to allow any
                                            client_id.
                                        </FieldDescription>
                                    </>
                                )}
                            </QuillSettingFormField>
                            {!idJagReady && (
                                <Item tone="info" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            XAA will not be enabled until you enter an IdP issuer URL. You can save
                                            partial settings as a draft.
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        Configure your IdP to grant <code>user:read</code> plus the scopes each
                                        integration needs (for project-scoped APIs, also <code>organization:read</code>{' '}
                                        and <code>project:read</code>). Tokens issued without the required scopes are
                                        rejected with an insufficient-scope error.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        </Form>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="primary"
                        loading={isIdJagConfigSubmitting}
                        disabledReason={configureIdJagModalLoading ? 'Loading XAA settings…' : undefined}
                        onClick={submitIdJagConfig}
                    >
                        Save settings
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
