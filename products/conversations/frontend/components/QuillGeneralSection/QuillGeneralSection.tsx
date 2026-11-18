import { IconPlus } from '@posthog/icons'
import { Button, Card, CardContent, Separator, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AuthorizedDomains } from '../../scenes/settings/AuthorizedDomains'
import { ChannelsSection } from '../../scenes/settings/ChannelsSection'
import { DraftModeSection } from '../../scenes/settings/DraftModeSection'
import { IdentityVerificationSecretSection } from '../../scenes/settings/IdentityVerificationSecretSection'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillSettingsSwitchRow } from '../QuillSettingsSwitchRow/QuillSettingsSwitchRow'

export function QuillGeneralSection({
    isEnabled,
    enabledLoading,
    teamsEnabled,
    showAddDomainButton,
    showDraftMode,
    onEnabledChange,
    onAddDomain,
}: {
    isEnabled: boolean
    enabledLoading: boolean
    teamsEnabled: boolean
    showAddDomainButton: boolean
    showDraftMode: boolean
    onEnabledChange: (checked: boolean) => void
    onAddDomain: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <QuillSettingsSubsection
                title="Enable support"
                description={
                    isEnabled
                        ? 'Master switch, channel setup, authorized domains, and credentials shared across every support channel.'
                        : 'Triage, assign, and automate support across in-app widget, email, Slack, Microsoft Teams, and direct API.'
                }
            >
                <Card size="sm" className="max-w-200">
                    <CardContent className="flex flex-col gap-3">
                        {!isEnabled && (
                            <>
                                <Text size="xs" render={<ul className="m-0 flex list-disc flex-col gap-1.5 pl-5" />}>
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
                                </Text>
                                <Separator />
                            </>
                        )}
                        <QuillSettingsSwitchRow
                            label={
                                isEnabled
                                    ? 'Turn off to stop accepting new tickets.'
                                    : 'Turn on to start accepting tickets.'
                            }
                            description={
                                isEnabled
                                    ? 'Existing tickets stay accessible.'
                                    : 'Configure notifications after enabling.'
                            }
                            checked={isEnabled}
                            onCheckedChange={onEnabledChange}
                            loading={enabledLoading}
                        />
                    </CardContent>
                </Card>
            </QuillSettingsSubsection>
            {isEnabled && (
                <>
                    <QuillSettingsSubsection
                        title="Channels"
                        description="Choose where customers can reach you. Each channel can be configured independently."
                    >
                        <Card size="sm" className="max-w-200">
                            <CardContent>
                                <ChannelsSection />
                            </CardContent>
                        </Card>
                    </QuillSettingsSubsection>
                    <QuillSettingsSubsection
                        title="Allowed domains"
                        description={
                            <>
                                Specify which domains can call the conversations API (widget and direct API). Leave
                                empty to allow all domains. Wildcards supported (e.g. <code>https://*.example.com</code>
                                ).{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/support/javascript-api"
                                            target="_blank"
                                        />
                                    }
                                >
                                    Docs
                                </Button>
                            </>
                        }
                    >
                        <Card size="sm" className="max-w-200">
                            <CardContent className="flex flex-col gap-2">
                                <AuthorizedDomains />
                                {showAddDomainButton && (
                                    <div>
                                        <Button variant="outline" onClick={onAddDomain}>
                                            <IconPlus />
                                            Add domain
                                        </Button>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    </QuillSettingsSubsection>
                    <QuillSettingsSubsection
                        title="Identity verification"
                        description={
                            <>
                                For logged-in users, sign their distinct_id on your backend with the identity
                                verification secret so tickets persist across browsers and devices without email
                                recovery.{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/support/javascript-api#user-identification"
                                            target="_blank"
                                        />
                                    }
                                >
                                    Read the docs
                                </Button>
                            </>
                        }
                    >
                        <Card size="sm" className="max-w-200">
                            <CardContent className="flex flex-col gap-2">
                                <Text size="xs" render={<p className="m-0" />}>
                                    Compute an HMAC-SHA256 of the user's <code>distinct_id</code> using the identity
                                    verification secret below (server-side) and pass both values to{' '}
                                    <code>posthog.init()</code>:
                                </Text>
                                <pre data-quill className="m-0 overflow-x-auto rounded-md bg-muted p-3 text-xs">
                                    {`posthog.init('<ph_project_api_key>', {
    identity_distinct_id: 'user_123',
    identity_hash: 'a1b2c3d4e5f6...',
})`}
                                </pre>
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Without identity verification, tickets are scoped to a browser session and users
                                    must recover them by email when switching devices.
                                </Text>
                            </CardContent>
                        </Card>
                    </QuillSettingsSubsection>
                    <IdentityVerificationSecretSection />
                    {showDraftMode && <DraftModeSection />}
                </>
            )}
        </div>
    )
}
