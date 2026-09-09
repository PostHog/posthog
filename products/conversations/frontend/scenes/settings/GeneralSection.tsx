import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Button, Card, CardContent, Separator, Spinner, Switch } from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { AuthorizedDomains } from './AuthorizedDomains'
import { ChannelsSection } from './ChannelsSection'
import { DraftModeSection } from './DraftModeSection'
import { SecretApiKeySection } from './SecretApiKeySection'
import { supportSettingsLogic } from './supportSettingsLogic'

export function GeneralSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { setConversationsEnabledLoading, setIsAddingDomain } = useActions(supportSettingsLogic)
    const { conversationsEnabledLoading, isAddingDomain, editingDomainIndex } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const teamsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]

    const isEnabled = !!currentTeam?.conversations_enabled

    return (
        <>
            <SceneSection
                title="Enable support"
                className="my-8"
                description={
                    isEnabled
                        ? 'Master switch, channel setup, authorized domains, and credentials shared across every support channel.'
                        : 'Triage, assign, and automate support across in-app widget, email, Slack, Microsoft Teams, and direct API.'
                }
            >
                <Card size="sm" className="max-w-[800px]">
                    <CardContent className="flex flex-col gap-y-3">
                        {!isEnabled && (
                            <>
                                <ul className="text-sm flex flex-col gap-1.5 mb-0 pl-5 list-disc">
                                    <li>
                                        <strong>In-app widget</strong> — embed a chat bubble on your site for logged-in
                                        or anonymous visitors.
                                    </li>
                                    <li>
                                        <strong>Email</strong> — forward customer emails to PostHog and reply directly
                                        from the inbox.
                                    </li>
                                    <li>
                                        <strong>Slack</strong> — turn Slack messages and reactions into tickets.
                                    </li>
                                    {teamsEnabled && (
                                        <li>
                                            <strong>Microsoft Teams</strong> — same workflow as Slack for Teams
                                            workspaces.
                                        </li>
                                    )}
                                    <li>
                                        <strong>Direct API</strong> — bring your own UI on top of the conversations API.
                                    </li>
                                </ul>
                                <Separator />
                            </>
                        )}
                        <div className="flex items-center gap-4 justify-between">
                            <div>
                                <label className="w-40 shrink-0 font-medium">
                                    {isEnabled
                                        ? 'Turn off to stop accepting new tickets.'
                                        : 'Turn on to start accepting tickets.'}
                                </label>
                                <p className="text-xs text-muted-alt mb-0">
                                    {isEnabled
                                        ? 'Existing tickets stay accessible.'
                                        : 'Configure notifications after enabling.'}
                                </p>
                            </div>
                            <div className="flex items-center gap-2">
                                {conversationsEnabledLoading ? <Spinner /> : null}
                                <Switch
                                    checked={isEnabled}
                                    disabled={conversationsEnabledLoading}
                                    onCheckedChange={(checked) => {
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
                                />
                            </div>
                        </div>
                    </CardContent>
                </Card>
            </SceneSection>
            {isEnabled && (
                <>
                    <SceneSection
                        title="Channels"
                        titleSize="sm"
                        className="my-8"
                        description="Choose where customers can reach you. Each channel can be configured independently."
                    >
                        <ChannelsSection />
                    </SceneSection>
                    <SceneSection
                        title="Allowed domains"
                        titleSize="sm"
                        className="my-8"
                        description={
                            <>
                                Specify which domains can call the conversations API (widget and direct API). Leave
                                empty to allow all domains. Wildcards supported (e.g. <code>https://*.example.com</code>
                                ).{' '}
                                <Link to="https://posthog.com/docs/support/javascript-api" target="_blank">
                                    Docs
                                </Link>
                            </>
                        }
                    >
                        <Card size="sm" className="max-w-[800px]">
                            <CardContent className="flex flex-col gap-y-2">
                                <AuthorizedDomains />
                                {!isAddingDomain && editingDomainIndex === null && (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="mt-2 self-start"
                                        onClick={() => setIsAddingDomain(true)}
                                    >
                                        <IconPlus />
                                        Add domain
                                    </Button>
                                )}
                            </CardContent>
                        </Card>
                    </SceneSection>
                    <SceneSection
                        title="Identity verification"
                        titleSize="sm"
                        className="my-8"
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
                        <Card size="sm" className="max-w-[800px]">
                            <CardContent>
                                <p className="mb-2">
                                    Compute an HMAC-SHA256 of the user's <code>distinct_id</code> using the secret API
                                    key below (server-side) and pass both values to <code>posthog.init()</code>:
                                </p>
                                <pre className="bg-surface-secondary rounded p-3 text-xs overflow-x-auto mb-2">
                                    {`posthog.init('<ph_project_api_key>', {
    identity_distinct_id: 'user_123',
    identity_hash: 'a1b2c3d4e5f6...',
})`}
                                </pre>
                                <p className="mb-0 text-xs text-muted-alt">
                                    Without identity verification, tickets are scoped to a browser session and users
                                    must recover them by email when switching devices.
                                </p>
                            </CardContent>
                        </Card>
                    </SceneSection>
                    <SecretApiKeySection />
                    <DraftModeSection />
                </>
            )}
        </>
    )
}
