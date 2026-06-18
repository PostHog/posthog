import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconCheckCircle } from '@posthog/icons'
import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { IntegrationDefinition, SettingsSectionComponent } from './integrationTypes'

export function IntegrationFullPage({
    definition,
    SettingsSection,
}: {
    definition: IntegrationDefinition
    SettingsSection: SettingsSectionComponent
}): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    const connected = getIntegrationsByKind([definition.kind]).length > 0

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
                        <ConnectedView definition={definition} />
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

            {/* onClickCapture fires before the connect button triggers its OAuth redirect */}
            <div onClickCapture={onConnectClick}>
                <SettingsSection next={urls.integration(definition.slug)} />
            </div>

            {definition.docsUrl ? (
                <Link to={definition.docsUrl} target="_blank" className="text-sm">
                    Learn more
                </Link>
            ) : null}
        </>
    )
}

function ConnectedView({ definition }: { definition: IntegrationDefinition }): JSX.Element {
    return (
        <>
            <IconCheckCircle className="text-success text-4xl" />

            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">You're connected to {definition.name}</h1>
                <p className="text-secondary m-0">Everything is set up and ready to go.</p>
            </div>

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
