import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonColorPicker, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import { supportSettingsLogic } from './supportSettingsLogic'

export const scene: SceneExport = {
    component: SupportSettingsScene,
    productKey: ProductKey.CONVERSATIONS,
}

function AuthorizedDomains(): JSX.Element {
    const { conversationsDomains, isAddingDomain, editingDomainIndex, domainInputValue } =
        useValues(supportSettingsLogic)
    const { setDomainInputValue, saveDomain, removeDomain, startEditDomain, cancelDomainEdit } =
        useActions(supportSettingsLogic)

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
                    <div className="gap-2">
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
                        <div className="flex gap-2 mt-2">
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
                </div>
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

export function SupportSettingsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const {
        generateNewToken,
        setIsAddingDomain,
        setConversationsEnabledLoading,
        setWidgetEnabledLoading,
        setGreetingInputValue,
        saveGreetingText,
        setNotificationRecipients,
    } = useActions(supportSettingsLogic)
    const {
        isAddingDomain,
        editingDomainIndex,
        conversationsEnabledLoading,
        widgetEnabledLoading,
        greetingInputValue,
        notificationRecipients,
    } = useValues(supportSettingsLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <div>
                <h2 className="flex gap-2 items-center">Conversations API</h2>
                <div className="flex flex-col gap-2">
                    <p>Turn on conversations API to enable access for tickets and messages.</p>
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
                        label={currentTeam?.conversations_enabled ? 'Conversations enabled' : 'Conversations disabled'}
                        loading={conversationsEnabledLoading}
                        bordered
                    />
                </div>
            </div>
            <div>
                {currentTeam?.conversations_enabled && (
                    <>
                        <div className="mb-8 mt-2 max-w-[800px]">
                            <h3>Email notifications</h3>
                            <p>Team members who will receive email notifications when new tickets are created.</p>
                            <MemberSelectMultiple
                                idKey="id"
                                value={notificationRecipients}
                                onChange={setNotificationRecipients}
                            />
                        </div>

                        <div>
                            <h3>In-app widget</h3>
                            <p>Turn on the in-app support widget to start receiving messages from your users</p>
                            <LemonSwitch
                                checked={!!currentTeam?.conversations_settings?.widget_enabled}
                                onChange={(checked) => {
                                    setWidgetEnabledLoading(true)
                                    updateCurrentTeam({
                                        conversations_settings: {
                                            ...currentTeam?.conversations_settings,
                                            widget_enabled: checked,
                                        },
                                    })
                                }}
                                label={
                                    currentTeam?.conversations_settings?.widget_enabled
                                        ? 'Widget enabled'
                                        : 'Widget disabled'
                                }
                                loading={widgetEnabledLoading}
                                bordered
                            />
                        </div>

                        {currentTeam?.conversations_settings?.widget_enabled && (
                            <div className="mt-8 flex flex-col gap-y-2 border rounded py-2 px-4 mb-2 max-w-[800px]">
                                <h3>Widget settings</h3>
                                <div className="flex items-center gap-4 py-2">
                                    <label className="w-40 shrink-0">Button color</label>
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
                                        selectedColor={currentTeam?.conversations_settings?.widget_color || '#1d4aff'}
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

                                <div className="flex items-center gap-4 py-2">
                                    <label className="w-40 shrink-0">Greeting message</label>
                                    <div className="flex gap-2 flex-1">
                                        <LemonInput
                                            value={
                                                greetingInputValue ??
                                                currentTeam?.conversations_settings?.widget_greeting_text ??
                                                'Hey, how can I help you today?'
                                            }
                                            placeholder="Enter greeting message"
                                            onChange={setGreetingInputValue}
                                            fullWidth
                                        />
                                        <LemonButton
                                            type="primary"
                                            onClick={saveGreetingText}
                                            disabledReason={
                                                !greetingInputValue ? 'Enter a greeting message' : undefined
                                            }
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                </div>

                                <div className="pt-8">
                                    <div className="flex justify-between items-center gap-4 py-2">
                                        <label className="w-40 shrink-0">Allowed domains</label>
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
                                    <p className="text-xs text-muted-alt mb-2">
                                        Specify which domains can show the conversations widget. Leave empty to show on
                                        all domains. Wildcards supported (e.g. https://*.example.com).
                                    </p>
                                    <AuthorizedDomains />
                                </div>

                                <div className="pt-8">
                                    <div className="flex items-center gap-4 py-2">
                                        <label className="w-40 shrink-0">Public token</label>
                                        <div className="flex gap-2 flex-1">
                                            <LemonInput
                                                value={
                                                    currentTeam?.conversations_settings?.widget_public_token ||
                                                    'Token will be auto-generated on save'
                                                }
                                                disabledReason="Read-only after generation"
                                                fullWidth
                                            />
                                            {currentTeam?.conversations_settings?.widget_public_token && (
                                                <LemonButton
                                                    type="secondary"
                                                    status="danger"
                                                    onClick={generateNewToken}
                                                >
                                                    Regenerate
                                                </LemonButton>
                                            )}
                                        </div>
                                    </div>
                                    <p className="text-xs text-muted-alt mb-2 ml-44">
                                        Automatically generated token used to authenticate widget requests.
                                    </p>
                                    <LemonBanner type="warning" className="my-2 ml-44">
                                        Only regenerate if you suspect it has been exposed or compromised.
                                    </LemonBanner>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
