import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Heading,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { RegisteredPartnerDetailsApi } from '~/generated/core/api.schemas'

import { AUTHENTICATION_LABELS, ORGANIZATION_LINK_LABELS } from './oauthApplicationLabels'

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="grid grid-cols-1 gap-1 @min-[36rem]/oauth-registration:grid-cols-[12rem_1fr]">
            <Text size="xs" variant="muted" render={<dt />}>
                {label}
            </Text>
            <Text size="xs" render={<dd className="m-0 min-w-0 break-words" />}>
                {children}
            </Text>
        </div>
    )
}

function Url({ value }: { value: string }): JSX.Element {
    return value ? (
        <Button
            variant="link"
            size="inline"
            className="break-all whitespace-normal text-left"
            render={<LinkPrimitive to={value} target="_blank" />}
        >
            {value}
        </Button>
    ) : (
        <Text size="xs" variant="muted" render={<span />}>
            Not set
        </Text>
    )
}

function List({ values }: { values: readonly string[] }): JSX.Element {
    return values.length ? (
        <ul className="m-0 p-0 list-none">
            {values.map((value) => (
                <li key={value} className="font-mono text-xs break-all">
                    {value}
                </li>
            ))}
        </ul>
    ) : (
        <Text size="xs" variant="muted" render={<span />}>
            None
        </Text>
    )
}

function Scopes({ registration }: { registration: RegisteredPartnerDetailsApi }): JSX.Element {
    if (!registration.uses_default_scopes) {
        return <List values={registration.scopes} />
    }
    return (
        <Collapsible>
            <CollapsibleHeader>
                <CollapsibleTrigger>{`PostHog's default set, ${registration.scopes.length} scopes`}</CollapsibleTrigger>
            </CollapsibleHeader>
            <CollapsibleContent className="pt-1">
                <List values={registration.scopes} />
            </CollapsibleContent>
        </Collapsible>
    )
}

export function QuillOAuthApplicationRegistration({
    clientId,
    registration,
}: {
    clientId: string
    registration: RegisteredPartnerDetailsApi
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3 @container/oauth-registration">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h2 className="m-0" />}>
                    What PostHog sees
                </Heading>
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    How PostHog treats the application now. The homepage, policy links and contacts come from your
                    metadata document as it was when the review opened. PostHog staff review the same details.
                </Text>
            </div>
            <dl className="m-0 flex flex-col gap-2 rounded-md border border-border p-3">
                <Field label="Client ID">
                    <span className="font-mono break-all">{clientId}</span>
                </Field>
                <Field label="Name">{registration.client_name}</Field>
                <Field label="Homepage">
                    <Url value={registration.client_uri} />
                </Field>
                <Field label="Logo">
                    <Url value={registration.logo_uri} />
                </Field>
                <Field label="Terms of service">
                    <Url value={registration.tos_uri} />
                </Field>
                <Field label="Privacy policy">
                    <Url value={registration.policy_uri} />
                </Field>
                <Field label="Contacts">
                    <List values={registration.contacts} />
                </Field>
                <Field label="Redirect URIs">
                    <List values={registration.redirect_uris} />
                </Field>
                <Field label="Authentication">{AUTHENTICATION_LABELS[registration.authentication]}</Field>
                <Field label="Public keys">
                    <Url value={registration.jwks_uri} />
                </Field>
                <Field label="Scopes">
                    <Scopes registration={registration} />
                </Field>
                <Field label="Provisioning">
                    {[
                        registration.can_create_accounts && 'Creates accounts',
                        registration.can_provision_resources && 'Provisions resources',
                    ]
                        .filter(Boolean)
                        .join(', ') || 'Nothing'}
                </Field>
                <Field label="Organization">{ORGANIZATION_LINK_LABELS[registration.organization_link]}</Field>
            </dl>
            {registration.metadata_document && (
                <Collapsible className="rounded-md border border-border p-2">
                    <CollapsibleHeader>
                        <CollapsibleTrigger>Your metadata document when the review opened</CollapsibleTrigger>
                    </CollapsibleHeader>
                    <CollapsibleContent className="pt-2">
                        <pre className="m-0 overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 font-mono text-xs">
                            {registration.metadata_document}
                        </pre>
                    </CollapsibleContent>
                </Collapsible>
            )}
        </section>
    )
}
