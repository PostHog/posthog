import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'

import {
    Button,
    Card,
    CardContent,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Item,
    ItemContent,
    Text,
} from '@posthog/quill'

import { proxyLogic } from './proxyLogic'

export function QuillProxyCreateRecordForm(): JSX.Element {
    const { formState, proxyRecordsLoading } = useValues(proxyLogic)
    const { collapseForm } = useActions(proxyLogic)

    return (
        <Card size="sm">
            <CardContent>
                {formState == 'active' && (
                    <Form
                        logic={proxyLogic}
                        formKey="createRecord"
                        enableFormOnSubmit
                        className="flex w-full flex-col gap-3"
                    >
                        <Item tone="warning" size="sm">
                            <ItemContent className="gap-1">
                                <Text size="xs" weight="semibold" render={<p className="m-0" />}>
                                    Avoid domains that ad-blockers may flag as analytics or advertising related.
                                </Text>
                                <Text size="xs" render={<ul className="m-0 flex list-disc flex-col gap-0.5 pl-5" />}>
                                    <li>
                                        <strong>Do not use</strong> subdomains containing words related to tracking,
                                        analytics, advertising, or PostHog (e.g. <code>analytics.mydomain.com</code>,{' '}
                                        <code>posthog.mydomain.com</code>, or <code>ph.mydomain.com</code>). These are
                                        commonly blocked by ad-blockers and will cause data loss. The proxy will{' '}
                                        <strong>NOT</strong> achieve the intended effect if ad-blockers are blocking the
                                        domain.
                                    </li>
                                    <li>
                                        <strong>Use a generic subdomain</strong> such as <code>t.mydomain.com</code>{' '}
                                        instead.
                                    </li>
                                </Text>
                            </ItemContent>
                        </Item>
                        <KeaField name="domain" noStyle>
                            {({ id, value, onChange, error }) => (
                                <Field data-invalid={error ? true : undefined}>
                                    <FieldLabel htmlFor={id}>Domain</FieldLabel>
                                    <Input
                                        id={id}
                                        autoFocus
                                        placeholder="Enter a domain (e.g. t.mydomain.com)"
                                        data-attr="domain-input"
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        aria-invalid={!!error}
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                        <div className="flex flex-wrap justify-end gap-2">
                            <Button
                                variant="outline"
                                onClick={collapseForm}
                                disabledReason={proxyRecordsLoading ? 'Saving' : undefined}
                            >
                                Cancel
                            </Button>
                            <Button
                                type="submit"
                                variant="primary"
                                data-attr="domain-save"
                                loading={proxyRecordsLoading}
                            >
                                Add
                            </Button>
                        </div>
                    </Form>
                )}
            </CardContent>
        </Card>
    )
}
