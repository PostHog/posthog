import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonColorPicker,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    Link,
} from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import { BrowserNotificationsSection } from './BrowserNotificationsSection'
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
        setIdentificationFormTitleValue,
        saveIdentificationFormTitle,
        setIdentificationFormDescriptionValue,
        saveIdentificationFormDescription,
        setPlaceholderTextValue,
        savePlaceholderText,
        setNotificationRecipients,
    } = useActions(supportSettingsLogic)
    const {
        isAddingDomain,
        editingDomainIndex,
        conversationsEnabledLoading,
        widgetEnabledLoading,
        greetingInputValue,
        identificationFormTitleValue,
        identificationFormDescriptionValue,
        placeholderTextValue,
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
            <SceneSection
                title="Conversations API"
                description="Turn on conversations API to enable access for tickets and messages."
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
            {currentTeam?.conversations_enabled && (
                <>
                    <SceneSection title="Notifications" className="mt-4">
                        <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                            <div className="flex items-center gap-4 justify-between">
                                <div>
                                    <label className="w-40 shrink-0 font-medium">Email notifications</label>
                                    <p className="text-xs text-muted-alt">
                                        Team members who will receive email notifications when new tickets are created.
                                    </p>
                                </div>
                                <MemberSelectMultiple
                                    idKey="id"
                                    value={notificationRecipients}
                                    onChange={setNotificationRecipients}
                                />
                            </div>
                            <LemonDivider />
                            <BrowserNotificationsSection />
                        </LemonCard>
                    </SceneSection>
                    <SceneSection title="In-app widget" className="mt-4">
                        <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                            <div className="flex items-center gap-4 justify-between">
                                <div>
                                    <label className="w-40 shrink-0 font-medium">Enable in-app widget</label>
                                    <p className="text-xs text-muted-alt">
                                        Turn on the in-app support widget to start receiving messages from your users
                                    </p>
                                </div>
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
                                    loading={widgetEnabledLoading}
                                />
                            </div>

                            {currentTeam?.conversations_settings?.widget_enabled && (
                                <>
                                    <LemonDivider />
                                    <div>
                                        <div className="flex justify-between items-center gap-4">
                                            <div>
                                                <label className="w-40 shrink-0 font-medium">Allowed domains</label>
                                                <p className="text-xs text-muted-alt">
                                                    Specify which domains can show the conversations widget. Leave empty
                                                    to show on all domains. Wildcards supported (e.g.
                                                    https://*.example.com).
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
                                    <SceneSection title="Visual settings" className="mt-8" titleSize="sm">
                                        <LemonCard hoverEffect={false} className="px-4 py-3">
                                            <div className="flex items-center gap-4 py-2 justify-between">
                                                <label className="w-40 shrink-0 font-medium">Button color</label>
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
                                            <LemonDivider />
                                            <div className="flex items-center gap-4 py-2 justify-between">
                                                <label className="w-40 shrink-0 font-medium">Widget position</label>
                                                <LemonSelect
                                                    value={
                                                        currentTeam?.conversations_settings?.widget_position ||
                                                        'bottom_right'
                                                    }
                                                    onChange={(value) => {
                                                        updateCurrentTeam({
                                                            conversations_settings: {
                                                                ...currentTeam?.conversations_settings,
                                                                widget_position: value,
                                                            },
                                                        })
                                                    }}
                                                    options={[
                                                        { value: 'bottom_right', label: 'Bottom right' },
                                                        { value: 'bottom_left', label: 'Bottom left' },
                                                        { value: 'top_right', label: 'Top right' },
                                                        { value: 'top_left', label: 'Top left' },
                                                    ]}
                                                />
                                            </div>
                                            <LemonDivider />
                                            <div className="flex items-center gap-4 py-2 justify-between">
                                                <label className="w-40 shrink-0 font-medium">Greeting message</label>
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
                                            <LemonDivider />
                                            <div className="flex items-center gap-4 py-2 justify-between">
                                                <label className="w-40 shrink-0 font-medium">Placeholder text</label>
                                                <div className="flex gap-2 flex-1">
                                                    <LemonInput
                                                        value={
                                                            placeholderTextValue ??
                                                            currentTeam?.conversations_settings
                                                                ?.widget_placeholder_text ??
                                                            'Type your message...'
                                                        }
                                                        placeholder="Enter placeholder text"
                                                        onChange={setPlaceholderTextValue}
                                                        fullWidth
                                                    />
                                                    <LemonButton
                                                        type="primary"
                                                        onClick={savePlaceholderText}
                                                        disabledReason={
                                                            !placeholderTextValue ? 'Enter placeholder text' : undefined
                                                        }
                                                    >
                                                        Save
                                                    </LemonButton>
                                                </div>
                                            </div>
                                        </LemonCard>
                                    </SceneSection>
                                    <SceneSection title="Identification form" className="mt-8" titleSize="sm">
                                        <LemonCard hoverEffect={false} className="px-4 py-3">
                                            <div className="flex items-center gap-4 py-2 justify-between">
                                                <div>
                                                    <label className="w-40 shrink-0 font-medium">Require email</label>
                                                    <p className="text-xs text-muted-alt mb-2">
                                                        Require user to enter their email address to start the chat.
                                                    </p>
                                                </div>
                                                <LemonSwitch
                                                    checked={
                                                        !!currentTeam?.conversations_settings?.widget_require_email
                                                    }
                                                    onChange={(checked) => {
                                                        updateCurrentTeam({
                                                            conversations_settings: {
                                                                ...currentTeam?.conversations_settings,
                                                                widget_require_email: checked,
                                                            },
                                                        })
                                                    }}
                                                />
                                            </div>

                                            {currentTeam?.conversations_settings?.widget_require_email && (
                                                <>
                                                    <LemonDivider />
                                                    <div className="flex items-center gap-4 py-2 justify-between">
                                                        <div>
                                                            <label className="w-40 shrink-0 font-medium">
                                                                Collect name
                                                            </label>
                                                            <p className="text-xs text-muted-alt mb-2">
                                                                Collect user's name to personalize the chat.
                                                            </p>
                                                        </div>
                                                        <LemonSwitch
                                                            checked={
                                                                !!currentTeam?.conversations_settings
                                                                    ?.widget_collect_name
                                                            }
                                                            onChange={(checked) => {
                                                                updateCurrentTeam({
                                                                    conversations_settings: {
                                                                        ...currentTeam?.conversations_settings,
                                                                        widget_collect_name: checked,
                                                                    },
                                                                })
                                                            }}
                                                        />
                                                    </div>
                                                    <LemonDivider />
                                                    <div className="flex items-center gap-4 py-2 justify-between">
                                                        <label className="w-40 shrink-0 font-medium">Form title</label>
                                                        <div className="flex gap-2 flex-1">
                                                            <LemonInput
                                                                value={
                                                                    identificationFormTitleValue ??
                                                                    currentTeam?.conversations_settings
                                                                        ?.widget_identification_form_title ??
                                                                    'Before we start...'
                                                                }
                                                                placeholder="Enter form title"
                                                                onChange={setIdentificationFormTitleValue}
                                                                fullWidth
                                                            />
                                                            <LemonButton
                                                                type="primary"
                                                                onClick={saveIdentificationFormTitle}
                                                                disabledReason={
                                                                    !identificationFormTitleValue
                                                                        ? 'Enter form title'
                                                                        : undefined
                                                                }
                                                            >
                                                                Save
                                                            </LemonButton>
                                                        </div>
                                                    </div>
                                                    <LemonDivider />
                                                    <div className="flex items-center gap-4 py-2 justify-between">
                                                        <label className="w-40 shrink-0 font-medium">
                                                            Form description
                                                        </label>
                                                        <div className="flex gap-2 flex-1">
                                                            <LemonInput
                                                                value={
                                                                    identificationFormDescriptionValue ??
                                                                    currentTeam?.conversations_settings
                                                                        ?.widget_identification_form_description ??
                                                                    'Please provide your details so we can help you better.'
                                                                }
                                                                placeholder="Enter form description"
                                                                onChange={setIdentificationFormDescriptionValue}
                                                                fullWidth
                                                            />
                                                            <LemonButton
                                                                type="primary"
                                                                onClick={saveIdentificationFormDescription}
                                                                disabledReason={
                                                                    !identificationFormDescriptionValue
                                                                        ? 'Enter form description'
                                                                        : undefined
                                                                }
                                                            >
                                                                Save
                                                            </LemonButton>
                                                        </div>
                                                    </div>
                                                </>
                                            )}
                                        </LemonCard>
                                    </SceneSection>
                                    <div className="pt-8">
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <div>
                                                <label className="w-40 shrink-0 font-medium">Public token</label>
                                                <p className="text-xs text-muted-alt mb-2">
                                                    Automatically generated token used to authenticate widget requests.
                                                </p>
                                            </div>
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
                                        <LemonBanner type="warning" className="my-2">
                                            Only regenerate if you suspect it has been exposed or compromised.
                                        </LemonBanner>
                                    </div>
                                </>
                            )}
                        </LemonCard>
                    </SceneSection>
                    <SceneSection
                        title="Workflows"
                        description={
                            <>
                                Use these events as triggers in <Link to="/workflows">Workflows</Link> to automate
                                ticket actions.
                            </>
                        }
                        className="mt-4"
                    >
                        <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                            <div className="flex flex-col gap-4">
                                <div>
                                    <h4 className="font-semibold mb-1">Trigger events</h4>
                                    <p className="text-xs text-muted-alt mb-2">
                                        These events are automatically captured when ticket or message state changes.
                                        Use them as workflow triggers.
                                    </p>
                                    <table className="w-full text-sm">
                                        <thead>
                                            <tr className="border-b">
                                                <th className="text-left py-1.5 pr-4 font-medium">Event</th>
                                                <th className="text-left py-1.5 font-medium">When</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <tr className="border-b">
                                                <td className="py-1.5 pr-4">
                                                    <code className="text-xs">$conversation_ticket_created</code>
                                                </td>
                                                <td className="py-1.5 text-xs text-muted-alt">
                                                    A customer opens a new ticket
                                                </td>
                                            </tr>
                                            <tr className="border-b">
                                                <td className="py-1.5 pr-4">
                                                    <code className="text-xs">$conversation_ticket_status_changed</code>
                                                </td>
                                                <td className="py-1.5 text-xs text-muted-alt">
                                                    Ticket status changes (e.g. new → pending → resolved)
                                                </td>
                                            </tr>
                                            <tr className="border-b">
                                                <td className="py-1.5 pr-4">
                                                    <code className="text-xs">
                                                        $conversation_ticket_priority_changed
                                                    </code>
                                                </td>
                                                <td className="py-1.5 text-xs text-muted-alt">
                                                    Ticket priority is set or changed
                                                </td>
                                            </tr>
                                            <tr className="border-b">
                                                <td className="py-1.5 pr-4">
                                                    <code className="text-xs">$conversation_ticket_assigned</code>
                                                </td>
                                                <td className="py-1.5 text-xs text-muted-alt">
                                                    Ticket is assigned to a team member
                                                </td>
                                            </tr>
                                            <tr className="border-b">
                                                <td className="py-1.5 pr-4">
                                                    <code className="text-xs">$conversation_message_sent</code>
                                                </td>
                                                <td className="py-1.5 text-xs text-muted-alt">
                                                    A team member sends a reply on a ticket
                                                </td>
                                            </tr>
                                            <tr>
                                                <td className="py-1.5 pr-4">
                                                    <code className="text-xs">$conversation_message_received</code>
                                                </td>
                                                <td className="py-1.5 text-xs text-muted-alt">
                                                    A customer sends a message on a ticket
                                                </td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>
                                <div>
                                    <h4 className="font-semibold mb-1">Workflow actions</h4>
                                    <p className="text-xs text-muted-alt">
                                        Use <strong>Get ticket</strong> to fetch current ticket data into workflow
                                        variables (ticket_status, ticket_priority, ticket_number, etc.) and{' '}
                                        <strong>Update ticket</strong> to change a ticket's status or priority.
                                    </p>
                                </div>
                            </div>
                        </LemonCard>
                    </SceneSection>
                </>
            )}
        </SceneContent>
    )
}
