import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
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
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import { AuthorizedDomains } from './AuthorizedDomains'
import { BrowserNotificationsSection } from './BrowserNotificationsSection'
import { EmailSection } from './EmailSection'
import { SecretApiKeySection } from './SecretApiKeySection'
import { SlackSection } from './SlackSection'
import { supportSettingsLogic } from './supportSettingsLogic'

export const scene: SceneExport = {
    component: SupportSettingsScene,
    productKey: ProductKey.CONVERSATIONS,
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
    const emailChannelEnabled = useFeatureFlag('PRODUCT_SUPPORT_EMAIL_CHANNEL')

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
            {currentTeam?.conversations_enabled && (
                <>
                    <SceneSection
                        title="Notifications"
                        className="mt-4"
                        description="We recommend using workflows to set custom notifications, e.g. when a new ticket is created or a new message is received."
                    >
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
                    <SlackSection />
                    {emailChannelEnabled && <EmailSection />}
                    <SceneSection
                        title="In-app widget"
                        description={
                            <>
                                Add a chat widget to your website for customers to reach you.{' '}
                                <Link to="https://posthog.com/docs/support/widget" target="_blank">
                                    Docs
                                </Link>
                            </>
                        }
                        className="mt-4"
                    >
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
                                ticket actions.{' '}
                                <Link to="https://posthog.com/docs/support/workflows" target="_blank">
                                    Docs
                                </Link>
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
                    <SecretApiKeySection />
                </>
            )}
        </SceneContent>
    )
}
