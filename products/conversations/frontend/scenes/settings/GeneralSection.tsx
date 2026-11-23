import { useActions, useValues } from 'kea'

import { LemonCard, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ChannelStatusList } from '../../components/ChannelStatusList/ChannelStatusList'
import { QuillGeneralSection } from '../../components/QuillGeneralSection/QuillGeneralSection'
import { DraftModeSection } from './DraftModeSection'
import { supportSettingsLogic } from './supportSettingsLogic'

export function GeneralSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { setConversationsEnabledLoading } = useActions(supportSettingsLogic)
    const { conversationsEnabledLoading } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const teamsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const isEnabled = !!currentTeam?.conversations_enabled

    const handleConversationsEnabledChange = (checked: boolean): void => {
        setConversationsEnabledLoading(true)
        updateCurrentTeam({
            conversations_enabled: checked,
            conversations_settings: {
                ...currentTeam?.conversations_settings,
                widget_enabled: checked ? currentTeam?.conversations_settings?.widget_enabled : false,
            },
        })
    }

    if (todayRailNav) {
        return (
            <QuillGeneralSection
                isEnabled={isEnabled}
                enabledLoading={conversationsEnabledLoading}
                teamsEnabled={teamsEnabled}
                // The send menu confirms every send, so the draft-mode default has nothing left to set.
                showDraftMode={!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_SIMPLIFIED_REPLIES]}
                onEnabledChange={handleConversationsEnabledChange}
            />
        )
    }

    return (
        <>
            <SceneSection
                title="Enable support"
                className="my-8"
                description={
                    isEnabled
                        ? 'Turn Support on or off for this project and see which channels are set up.'
                        : 'Triage, assign, and automate support across in-app widget, email, Slack, Microsoft Teams, and direct API.'
                }
            >
                <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                    {!isEnabled && (
                        <>
                            <ul className="text-sm flex flex-col gap-1.5 mb-0 pl-5 list-disc">
                                <li>
                                    <strong>In-app widget</strong> — embed a chat bubble on your site for logged-in or
                                    anonymous visitors.
                                </li>
                                <li>
                                    <strong>Email</strong> — forward customer emails to PostHog and reply directly from
                                    the inbox.
                                </li>
                                <li>
                                    <strong>Slack</strong> — turn Slack messages and reactions into tickets.
                                </li>
                                {teamsEnabled && (
                                    <li>
                                        <strong>Microsoft Teams</strong> — same workflow as Slack for Teams workspaces.
                                    </li>
                                )}
                                <li>
                                    <strong>Direct API</strong> — bring your own UI on top of the conversations API.
                                </li>
                            </ul>
                            <LemonDivider />
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
                        <LemonSwitch
                            checked={isEnabled}
                            onChange={handleConversationsEnabledChange}
                            loading={conversationsEnabledLoading}
                        />
                    </div>
                </LemonCard>
            </SceneSection>
            {isEnabled && (
                <>
                    <SceneSection
                        title="Channels"
                        titleSize="sm"
                        className="my-8"
                        description="Where customers can reach you. Open a channel to set it up or change it."
                    >
                        <ChannelStatusList />
                    </SceneSection>
                    {/* The send menu confirms every send, so the draft-mode default has nothing left to set. */}
                    {!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_SIMPLIFIED_REPLIES] && <DraftModeSection />}
                </>
            )}
        </>
    )
}
