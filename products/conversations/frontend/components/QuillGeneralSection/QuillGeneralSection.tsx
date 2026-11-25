import { Card, CardContent, Separator, Text } from '@posthog/quill'

import { DraftModeSection } from '../../scenes/settings/DraftModeSection'
import { ChannelStatusList } from '../ChannelStatusList/ChannelStatusList'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillSettingsSwitchRow } from '../QuillSettingsSwitchRow/QuillSettingsSwitchRow'

export function QuillGeneralSection({
    isEnabled,
    enabledLoading,
    teamsEnabled,
    showDraftMode,
    onEnabledChange,
}: {
    isEnabled: boolean
    enabledLoading: boolean
    teamsEnabled: boolean
    showDraftMode: boolean
    onEnabledChange: (checked: boolean) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <QuillSettingsSubsection
                title="Enable support"
                description={
                    isEnabled
                        ? 'Turn Support on or off for this project and see which channels are set up.'
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
                        description="Where customers can reach you. Open a channel to set it up or change it."
                    >
                        <ChannelStatusList />
                    </QuillSettingsSubsection>
                    {showDraftMode && <DraftModeSection />}
                </>
            )}
        </div>
    )
}
