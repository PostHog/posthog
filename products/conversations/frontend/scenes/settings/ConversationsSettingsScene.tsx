import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonColorPicker, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'
import { conversationsSettingsLogic } from './conversationsSettingsLogic'

export const scene: SceneExport = {
    component: ConversationsSettingsScene,
}

function ConversationsAuthorizedDomains(): JSX.Element {
    const { conversationsDomains, isAddingDomain, editingDomainIndex, domainInputValue } =
        useValues(conversationsSettingsLogic)
    const { setIsAddingDomain, setDomainInputValue, saveDomain, removeDomain, startEditDomain, cancelDomainEdit } =
        useActions(conversationsSettingsLogic)

    return (
        <div className="flex flex-col gap-2">
            {conversationsDomains.length === 0 && !isAddingDomain && (
                <div className="border rounded p-4 text-secondary">
                    <p className="mb-0">
                        <span className="font-bold">No domains configured.</span>
                        <br />
                        The widget will show on all domains. Add domains to limit where it appears.
                    </p>
                </div>
            )}

            {(isAddingDomain || editingDomainIndex !== null) && (
                <div className="border rounded p-2 bg-surface-primary">
                    <div className="flex gap-2">
                        <LemonInput
                            autoFocus
                            value={domainInputValue}
                            onChange={setDomainInputValue}
                            placeholder="https://example.com or https://*.example.com"
                            fullWidth
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    saveDomain(domainInputValue, editingDomainIndex)
                                } else if (e.key === 'Escape') {
                                    cancelDomainEdit()
                                }
                            }}
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => saveDomain(domainInputValue, editingDomainIndex)}
                            disabledReason={!domainInputValue.trim() ? 'Enter a domain' : undefined}
                        >
                            Save
                        </LemonButton>
                        <LemonButton type="secondary" size="small" onClick={cancelDomainEdit}>
                            Cancel
                        </LemonButton>
                    </div>
                </div>
            )}

            {!isAddingDomain && editingDomainIndex === null && (
                <LemonButton
                    className="max-w-80"
                    onClick={() => setIsAddingDomain(true)}
                    type="secondary"
                    icon={<IconPlus />}
                    size="small"
                >
                    Add domain
                </LemonButton>
            )}

            {conversationsDomains.map((domain: string, index: number) =>
                editingDomainIndex === index ? null : (
                    <div key={index} className="border rounded flex items-center p-2 pl-4 bg-surface-primary">
                        <span title={domain} className="flex-1 truncate">
                            {domain}
                        </span>
                        <div className="flex gap-1 shrink-0">
                            <LemonButton
                                icon={<IconPencil />}
                                onClick={() => startEditDomain(index)}
                                tooltip="Edit"
                                size="small"
                            />
                            <LemonButton
                                icon={<IconTrash />}
                                tooltip="Remove domain"
                                size="small"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: <>Remove {domain}?</>,
                                        description: 'Are you sure you want to remove this domain?',
                                        primaryButton: {
                                            status: 'danger',
                                            children: 'Remove',
                                            onClick: () => removeDomain(index),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                            />
                        </div>
                    </div>
                )
            )}
        </div>
    )
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
                                Turn on conversations to enable API access for tickets and messages
                            </p>
                        </div>
                        <LemonSwitch
                            checked={!!currentTeam?.conversations_enabled}
                            onChange={(checked) => {
                                updateCurrentTeam({
                                    conversations_enabled: checked,
                                })
                            }}
                            label={currentTeam?.conversations_enabled ? 'Enabled' : 'Disabled'}
                            loading={currentTeamLoading}
                        />
                    </div>

                    {currentTeam?.conversations_enabled && (
                        <>
                            <div className="flex items-center justify-between pt-4 border-t">
                                <div>
                                    <h4 className="text-base font-semibold">Enable widget</h4>
                                    <p className="text-sm text-muted-alt">
                                        Turn on the conversations widget to start receiving messages from your users
                                    </p>
                                </div>
                                <LemonSwitch
                                    checked={!!currentTeam?.conversations_settings?.widget_enabled}
                                    onChange={(checked) => {
                                        updateCurrentTeam({
                                            conversations_settings: {
                                                ...currentTeam?.conversations_settings,
                                                widget_enabled: checked,
                                            },
                                        })
                                    }}
                                    label={currentTeam?.conversations_settings?.widget_enabled ? 'Enabled' : 'Disabled'}
                                    loading={currentTeamLoading}
                                />
                            </div>

                            {currentTeam?.conversations_settings?.widget_enabled && (
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
                                                selectedColor={
                                                    currentTeam?.conversations_settings?.widget_color || '#1d4aff'
                                                }
                                                onSelectColor={(color) => {
                                                    updateCurrentTeam({
                                                        conversations_settings: {
                                                            ...currentTeam?.conversations_settings,
                                                            widget_color: color,
                                                        },
                                                    })
                                                }}
                                                showCustomColor
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <label className="text-sm font-medium">Greeting message</label>
                                            <LemonInput
                                                value={
                                                    currentTeam?.conversations_settings?.widget_greeting_text ||
                                                    'Hey, how can I help you today?'
                                                }
                                                placeholder="Enter greeting message"
                                                onChange={(value) => {
                                                    updateCurrentTeam({
                                                        conversations_settings: {
                                                            ...currentTeam?.conversations_settings,
                                                            widget_greeting_text: value,
                                                        },
                                                    })
                                                }}
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-2 pt-8">
                                        <label className="text-sm font-medium">Allowed domains</label>
                                        <p className="text-xs text-muted-alt">
                                            Specify which domains can show the conversations widget. Leave empty to show
                                            on all domains. Wildcards supported (e.g. https://*.example.com).
                                        </p>
                                        <ConversationsAuthorizedDomains />
                                    </div>

                                    <div className="space-y-2 pt-8">
                                        <label className="text-sm font-medium">Public token</label>
                                        <p className="text-xs text-muted-alt mb-2">
                                            Automatically generated when you enable conversations. Regenerate if
                                            compromised.
                                        </p>
                                        <div className="flex gap-2">
                                            <LemonInput
                                                value={
                                                    currentTeam?.conversations_settings?.widget_public_token ||
                                                    'Token will be auto-generated on save'
                                                }
                                                disabledReason="Read-only after generation"
                                                fullWidth
                                            />
                                            {currentTeam?.conversations_settings?.widget_public_token && (
                                                <LemonButton type="secondary" onClick={generateNewToken}>
                                                    Regenerate
                                                </LemonButton>
                                            )}
                                        </div>
                                    </div>
                                </>
                            )}
                        </>
                    )}
                </LemonCard>
            </div>
        </SceneContent>
    )
}
