import { LemonButton, LemonDialog, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { teamLogic } from 'scenes/teamLogic'

export type FeatureFlagSettingsProps = {
    inModal?: boolean
}

export function FeatureFlagSettings({ inModal = false }: FeatureFlagSettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-8">
            <div className="space-y-2">
                <LemonSwitch
                    data-attr="default-flag-persistence-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            flags_persistence_default: checked,
                        })
                    }}
                    label="Enable flag persistence by default"
                    bordered={!inModal}
                    fullWidth={inModal}
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    checked={!!currentTeam?.flags_persistence_default}
                />

                <p>
                    When enabled, all new feature flags will have persistence enabled by default. This ensures
                    consistent user experiences across authentication steps. Learn more in our{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                        target="_blank"
                    >
                        documentation
                    </Link>
                    .
                </p>
            </div>
            <div className="space-y-2">
                <FlagDefinitionsAPIKey />
            </div>
        </div>
    )
}

export function FlagDefinitionsAPIKey(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetSecretToken } = useActions(teamLogic)

    const openResetProjectSecretApiKeyDialog = (): void => {
        LemonDialog.open({
            title: 'Reset Flag Definitions API key?',
            description: 'This will invalidate the current Flag Definitions API key and cannot be undone.',
            primaryButton: {
                children: 'Reset',
                type: 'primary',
                onClick: resetSecretToken,
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'secondary',
            },
        })
    }

    return (
        <>
            <h2 id="secret-api-key" className="min-w-[25rem]">
                Flag Definitions API key
            </h2>
            <p>
                Use this key to retrieve feature flag definitions for{' '}
                <Link to="https://posthog.com/docs/feature-flags/local-evaluation">local evaluation</Link>.
            </p>
            <CodeSnippet
                actions={
                    isTeamTokenResetAvailable ? (
                        <LemonButton icon={<IconRefresh />} noPadding onClick={openResetProjectSecretApiKeyDialog} />
                    ) : undefined
                }
                thing="Flag Definitions API key"
            >
                {currentTeam?.secret_api_token || ''}
            </CodeSnippet>
            <p>
                This key replaces personal API keys for local evaluation. Existing personal API keys will continue to
                work, but we recommend migrating to this new key. Keep this key private.
            </p>
        </>
    )
}

export function openFeatureFlagSettingsDialog(): void {
    LemonDialog.open({
        title: 'Feature flag settings',
        content: <FeatureFlagSettings inModal />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
