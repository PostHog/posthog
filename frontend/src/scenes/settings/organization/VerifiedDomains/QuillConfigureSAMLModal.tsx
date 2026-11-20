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
    Input,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
    Textarea,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillCopyField } from 'scenes/settings/components/QuillCopyField'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function QuillConfigureSAMLModal({
    siteUrl,
    samlReady,
    onClose,
}: {
    siteUrl: string
    samlReady: boolean
    onClose: () => void
}): JSX.Element {
    const { configureSAMLModalId, configureSAMLModalLoading, isSamlConfigSubmitting, samlConfig } =
        useValues(verifiedDomainsLogic)
    const { submitSamlConfig } = useActions(verifiedDomainsLogic)

    return (
        <Dialog open={!!configureSAMLModalId} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>Configure SAML authentication and provisioning</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    {configureSAMLModalLoading ? (
                        <Skeleton className="h-40 w-full" />
                    ) : (
                        <Form
                            logic={verifiedDomainsLogic}
                            formKey="samlConfig"
                            enableFormOnSubmit
                            className="flex flex-col gap-4"
                        >
                            <Text size="xs" render={<p className="m-0" />}>
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/data/sso#setting-up-saml"
                                            target="_blank"
                                        />
                                    }
                                >
                                    Read the docs
                                </Button>
                            </Text>
                            <QuillCopyField label="ACS Consumer URL" value={`${siteUrl}/complete/saml/`} />
                            <QuillCopyField label="RelayState" value={samlConfig.saml_relay_state || 'unknown'} />
                            <QuillCopyField label="Audience / Entity ID" value={siteUrl} />
                            <QuillSettingFormField name="saml_acs_url" label="SAML ACS URL">
                                {({ id, value, onChange, invalid }) => (
                                    <Input
                                        id={id}
                                        className="ph-ignore-input"
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="Your IdP's ACS or single sign-on URL."
                                        aria-invalid={invalid || undefined}
                                    />
                                )}
                            </QuillSettingFormField>
                            <QuillSettingFormField name="saml_entity_id" label="SAML Entity ID">
                                {({ id, value, onChange, invalid }) => (
                                    <Input
                                        id={id}
                                        className="ph-ignore-input"
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="Entity ID provided by your IdP."
                                        aria-invalid={invalid || undefined}
                                    />
                                )}
                            </QuillSettingFormField>
                            <QuillSettingFormField name="saml_x509_cert" label="SAML X.509 Certificate">
                                {({ id, value, onChange, invalid }) => (
                                    <Textarea
                                        id={id}
                                        className="ph-ignore-input"
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        rows={10}
                                        placeholder={`Enter the public certificate of your IdP. Keep all line breaks.\n-----BEGIN CERTIFICATE-----\nMIICVjCCAb+gAwIBAgIBADANBgkqhkiG9w0BAQ0FADBIMQswCQYDVQQGEwJ1czEL\n-----END CERTIFICATE-----`}
                                        aria-invalid={invalid || undefined}
                                    />
                                )}
                            </QuillSettingFormField>
                            {!samlReady && (
                                <Item tone="info" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            SAML will not be enabled unless you enter all attributes above. However you
                                            can still settings as draft.
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                        </Form>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="primary"
                        loading={isSamlConfigSubmitting}
                        disabledReason={configureSAMLModalLoading ? 'Loading SAML settings…' : undefined}
                        onClick={submitSamlConfig}
                    >
                        Save settings
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
