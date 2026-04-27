import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { AuthorizedDomains } from './AuthorizedDomains'
import { SecretApiKeySection } from './SecretApiKeySection'
import { supportSettingsLogic } from './supportSettingsLogic'

export function ApiSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { setConversationsEnabledLoading, setIsAddingDomain } = useActions(supportSettingsLogic)
    const { conversationsEnabledLoading, isAddingDomain, editingDomainIndex } = useValues(supportSettingsLogic)

    const isEnabled = !!currentTeam?.conversations_enabled

    return (
        <SceneSection
            title="Conversations API"
            description={
                <>
                    Turn on conversations API to enable access for tickets and messages.{' '}
                    <Link to="https://posthog.com/docs/support/javascript-api" target="_blank">
                        Docs
                    </Link>
                </>
            }
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="w-40 shrink-0 font-medium">Enable conversations API</label>
                    </div>
                    <LemonSwitch
                        checked={isEnabled}
                        onChange={(checked) => {
                            setConversationsEnabledLoading(true)
                            updateCurrentTeam({
                                conversations_enabled: checked,
                                conversations_settings: {
                                    ...currentTeam?.conversations_settings,
                                    widget_enabled: checked
                                        ? currentTeam?.conversations_settings?.widget_enabled
                                        : false,
                                },
                            })
                        }}
                        loading={conversationsEnabledLoading}
                    />
                </div>

                {isEnabled && (
                    <>
                        <LemonDivider />
                        <div>
                            <div className="flex justify-between items-center gap-4">
                                <div>
                                    <label className="w-40 shrink-0 font-medium">Allowed domains</label>
                                    <p className="text-xs text-muted-alt">
                                        Specify which domains can call the conversations API (widget and direct API).
                                        Leave empty to allow all domains. Wildcards supported (e.g.{' '}
                                        <code>https://*.example.com</code>).
                                    </p>
                                </div>
                                {!isAddingDomain && editingDomainIndex === null && (
                                    <LemonButton
                                        onClick={() => setIsAddingDomain(true)}
                                        type="secondary"
                                        icon={<IconPlus />}
                                        size="small"
                                    >
                                        Add domain
                                    </LemonButton>
                                )}
                            </div>
                            <AuthorizedDomains />
                        </div>
                    </>
                )}
            </LemonCard>

            {isEnabled && (
                <SceneSection
                    title="Identity verification"
                    description={
                        <>
                            For logged-in users, sign their distinct_id on your backend with the secret API key so
                            tickets persist across browsers and devices without email recovery.{' '}
                            <Link
                                to="https://posthog.com/docs/support/javascript-api#user-identification"
                                target="_blank"
                                targetBlankIcon
                            >
                                Read the docs
                            </Link>
                        </>
                    }
                >
                    <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                        <p className="mb-2">
                            Compute an HMAC-SHA256 of the user's <code>distinct_id</code> using the secret API key above
                            (server-side) and pass both values to <code>posthog.init()</code>:
                        </p>
                        <pre className="bg-surface-secondary rounded p-3 text-xs overflow-x-auto mb-2">
                            {`posthog.init('<ph_project_api_key>', {
    identity_distinct_id: 'user_123',
    identity_hash: 'a1b2c3d4e5f6...',
})`}
                        </pre>
                        <p className="mb-0 text-xs text-muted-alt">
                            Without identity verification, tickets are scoped to a browser session and users must
                            recover them by email when switching devices.
                        </p>
                    </LemonCard>
                    <SecretApiKeySection />
                </SceneSection>
            )}
        </SceneSection>
    )
}
