import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTextArea, Link, Spinner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { IntegrationDefinition, IntegrationStatus, SettingsSectionComponent } from './integrationTypes'

export function IntegrationFullPage({
    definition,
    SettingsSection,
}: {
    definition: IntegrationDefinition
    SettingsSection: SettingsSectionComponent
}): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    const integrations = getIntegrationsByKind([definition.kind])
    const connected = integrations.length > 0

    return (
        <div className="flex flex-col items-center justify-center min-h-full w-full p-4">
            <div className="flex flex-col items-center gap-4 max-w-160 w-full bg-surface-primary border rounded-lg overflow-hidden shadow-sm">
                {definition.banner ? (
                    <img src={definition.banner} alt={`${definition.name} banner`} className="w-full object-cover" />
                ) : null}

                <div className="flex flex-col items-center gap-4 w-full px-8 pb-8 pt-2">
                    <div className="flex items-center justify-center w-16 h-16 rounded-lg bg-white border p-2.5">
                        <img
                            src={definition.logo}
                            alt={`${definition.name} logo`}
                            className="max-w-full max-h-full object-contain"
                        />
                    </div>

                    {integrationsLoading ? (
                        <Spinner className="text-2xl" />
                    ) : connected ? (
                        <ConnectedView definition={definition} integrations={integrations} />
                    ) : (
                        <ConnectView definition={definition} SettingsSection={SettingsSection} />
                    )}
                </div>
            </div>

            <Link to={urls.projectHomepage()} className="flex items-center gap-1 mt-6 text-secondary">
                <IconArrowLeft />
                Back to PostHog
            </Link>
        </div>
    )
}

function ConnectView({
    definition,
    SettingsSection,
}: {
    definition: IntegrationDefinition
    SettingsSection: SettingsSectionComponent
}): JSX.Element {
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    // Connecting an integration requires project membership (enforced again in the backend);
    // editing or removing one still requires admin. Users with no project access fall back to
    // the request-access flow below.
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    const onConnectClick = (): void => {
        reportIntegrationConnectClicked(definition.slug, definition.kind)
    }

    return (
        <>
            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">Connect {definition.name}</h1>
                <p className="text-secondary m-0">{definition.subtitle}</p>
            </div>

            <div className="text-center text-sm">{definition.description}</div>

            {restrictionReason ? (
                <RequestAccessSection definition={definition} />
            ) : (
                // onClickCapture fires before the connect button triggers its OAuth redirect
                <div onClickCapture={onConnectClick}>
                    <SettingsSection next={urls.integration(definition.slug)} />
                </div>
            )}

            {definition.docsUrl ? (
                <Link to={definition.docsUrl} target="_blank" className="text-sm">
                    Learn more
                </Link>
            ) : null}
        </>
    )
}

function RequestAccessSection({ definition }: { definition: IntegrationDefinition }): JSX.Element {
    const { accessRequestReason, accessRequestLoading, requestedAccessKinds } = useValues(integrationsLogic)
    const { setAccessRequestReason, requestIntegrationAccess } = useActions(integrationsLogic)

    if (requestedAccessKinds.includes(definition.kind)) {
        return (
            <LemonBanner type="success" className="w-full">
                Request sent. Your project admins have been notified and can connect {definition.name}.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-3 w-full">
            <LemonBanner type="info" className="w-full">
                Connecting {definition.name} requires admin access. Tell your project admins why you need it and we'll
                email them.
            </LemonBanner>
            <LemonTextArea
                value={accessRequestReason}
                onChange={setAccessRequestReason}
                placeholder={`Why does your team need ${definition.name}?`}
                minRows={3}
                maxLength={2000}
            />
            <LemonButton
                type="primary"
                fullWidth
                center
                loading={accessRequestLoading}
                disabledReason={!accessRequestReason.trim() ? 'Add a short note for your admins' : undefined}
                onClick={() => requestIntegrationAccess({ kind: definition.kind })}
            >
                Request {definition.name}
            </LemonButton>
        </div>
    )
}

function ConnectedView({
    definition,
    integrations,
}: {
    definition: IntegrationDefinition
    integrations: IntegrationType[]
}): JSX.Element {
    const PostConnect = definition.PostConnect
    // Default to ``ok`` when no status hook is provided so today's integrations keep their
    // current "Everything is set up" copy without each having to opt in.
    const status: IntegrationStatus = definition.useStatus?.(integrations) ?? 'ok'
    const ok = status === 'ok'

    return (
        <>
            {ok ? (
                <IconCheckCircle className="text-success text-4xl" />
            ) : (
                <IconWarning className="text-warning text-4xl" />
            )}

            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">
                    {ok ? `You're connected to ${definition.name}` : `${definition.name} is connected, with caveats`}
                </h1>
                <p className="text-secondary m-0">
                    {ok
                        ? 'Everything is set up and ready to go.'
                        : PostConnect
                          ? 'Review the items below before using it.'
                          : 'Some settings may need your attention.'}
                </p>
            </div>

            {PostConnect ? (
                <div className="w-full flex flex-col gap-2">
                    {integrations.map((integration) => (
                        <PostConnect key={integration.id} integration={integration} />
                    ))}
                </div>
            ) : null}

            {definition.capabilities.length > 0 ? (
                <div className="w-full">
                    <p className="font-semibold mb-2">What you can do now</p>
                    <ul className="flex flex-col gap-1">
                        {definition.capabilities.map((capability) => (
                            <li key={capability} className="flex items-start gap-2">
                                <IconCheckCircle className="text-success mt-0.5 shrink-0" />
                                <span>{capability}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}

            <LemonButton type="primary" to={urls.projectHomepage()}>
                Go to PostHog
            </LemonButton>
        </>
    )
}
