import { LemonCollapse, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { RegisteredPartnerDetailsApi } from '~/generated/core/api.schemas'

import { AUTHENTICATION_LABELS, ORGANIZATION_LINK_LABELS } from './oauthApplicationLabels'

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="grid grid-cols-1 gap-1 @min-[36rem]/oauth-registration:grid-cols-[12rem_1fr]">
            <dt className="text-secondary">{label}</dt>
            <dd className="m-0 min-w-0 break-words">{children}</dd>
        </div>
    )
}

function Url({ value }: { value: string }): JSX.Element {
    return value ? (
        <Link to={value} target="_blank" className="break-all">
            {value}
        </Link>
    ) : (
        <span className="text-secondary">Not set</span>
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
        <span className="text-secondary">None</span>
    )
}

function Scopes({ registration }: { registration: RegisteredPartnerDetailsApi }): JSX.Element {
    if (!registration.uses_default_scopes) {
        return <List values={registration.scopes} />
    }
    return (
        <LemonCollapse
            size="small"
            panels={[
                {
                    key: 'scopes',
                    header: `PostHog's default set, ${registration.scopes.length} scopes`,
                    content: <List values={registration.scopes} />,
                },
            ]}
        />
    )
}

export function OAuthApplicationRegistration({
    clientId,
    registration,
}: {
    clientId: string
    registration: RegisteredPartnerDetailsApi
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3 @container/oauth-registration">
            <div>
                <h2 className="text-lg font-semibold m-0">What PostHog sees</h2>
                <p className="text-secondary m-0">
                    How PostHog treats the application now. The homepage, policy links and contacts come from your
                    metadata document as it was when the review opened. PostHog staff review the same details.
                </p>
            </div>
            <dl className="m-0 flex flex-col gap-2 border rounded p-3 bg-surface-primary">
                <Field label="Client ID">
                    <span className="font-mono text-xs break-all">{clientId}</span>
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
                <LemonCollapse
                    panels={[
                        {
                            key: 'document',
                            header: 'Your metadata document when the review opened',
                            content: (
                                <CodeSnippet language={Language.JSON} wrap>
                                    {registration.metadata_document}
                                </CodeSnippet>
                            ),
                        },
                    ]}
                />
            )}
        </section>
    )
}
