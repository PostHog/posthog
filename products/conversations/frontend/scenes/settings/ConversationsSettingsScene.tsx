import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonColorPicker, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'
import { conversationsSettingsLogic } from './conversationsSettingsLogic'

export const scene: SceneExport = {
    component: ConversationsSettingsScene,
}

export function ConversationsSettingsScene(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { generateNewToken } = useActions(conversationsSettingsLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Conversations"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />

            <div className="space-y-4">
                <LemonCard hoverEffect={false}>
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="text-lg font-semibold">Enable conversations</h3>
                            <p className="text-sm text-muted-alt">
                                Turn on the conversations widget to start receiving messages from your users
                            </p>
                        </div>
                        <LemonSwitch
                            checked={!!currentTeam?.conversations_enabled}
                            onChange={(checked) => {
                                updateCurrentTeam({ conversations_enabled: checked })
                            }}
                            label={currentTeam?.conversations_enabled ? 'Enabled' : 'Disabled'}
                            loading={currentTeamLoading}
                        />
                    </div>

                    {currentTeam?.conversations_enabled && (
                        <>
                            <div className="space-y-4 pt-4 border-t">
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Button color</label>
                                    <LemonColorPicker
                                        colors={[
                                            '#1d4aff',
                                            '#00aaff',
                                            '#00cc44',
                                            '#ffaa00',
                                            '#ff4444',
                                            '#9b59b6',
                                            '#1abc9c',
                                            '#000000',
                                        ]}
                                        selectedColor={currentTeam?.conversations_color || '#1d4aff'}
                                        onSelectColor={(color) => {
                                            updateCurrentTeam({ conversations_color: color })
                                        }}
                                        showCustomColor
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-sm font-medium">Greeting message</label>
                                    <LemonInput
                                        value={
                                            currentTeam?.conversations_greeting_text || 'Hey, how can I help you today?'
                                        }
                                        placeholder="Enter greeting message"
                                        onChange={(value) => {
                                            updateCurrentTeam({ conversations_greeting_text: value })
                                        }}
                                    />
                                </div>
                            </div>

                            <div className="space-y-2 pt-8">
                                <label className="text-sm font-medium">Authorized domains</label>
                                <p className="text-xs text-muted-alt">
                                    Restrict which domains can display the conversations widget. Leave empty to allow
                                    all domains. Wildcards are supported (e.g. https://*.example.com).
                                </p>
                                <AuthorizedUrlList
                                    type={AuthorizedUrlListType.CONVERSATIONS_WIDGET}
                                    addText="Add authorized domain"
                                    showLaunch={false}
                                    displaySuggestions={false}
                                    addButtonClassName="max-w-80"
                                />
                            </div>

                            <div className="space-y-2 pt-8">
                                <label className="text-sm font-medium">Public token</label>
                                <p className="text-xs text-muted-alt mb-2">
                                    Automatically generated when you enable conversations. Regenerate if compromised.
                                </p>
                                <div className="flex gap-2">
                                    <LemonInput
                                        value={
                                            currentTeam?.conversations_public_token ||
                                            'Token will be auto-generated on save'
                                        }
                                        disabledReason="Read-only after generation"
                                        fullWidth
                                    />
                                    {currentTeam?.conversations_public_token && (
                                        <LemonButton type="secondary" onClick={generateNewToken}>
                                            Regenerate
                                        </LemonButton>
                                    )}
                                </div>
                            </div>
                        </>
                    )}
                </LemonCard>
            </div>
        </SceneContent>
    )
}
