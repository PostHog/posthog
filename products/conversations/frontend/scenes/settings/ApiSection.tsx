import { useActions, useValues } from 'kea'

import { LemonCard, LemonSwitch, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function ApiSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { setConversationsEnabledLoading } = useActions(supportSettingsLogic)
    const { conversationsEnabledLoading } = useValues(supportSettingsLogic)

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
            <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="w-40 shrink-0 font-medium">Enable conversations API</label>
                    </div>
                    <LemonSwitch
                        checked={!!currentTeam?.conversations_enabled}
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
            </LemonCard>
        </SceneSection>
    )
}
