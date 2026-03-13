import { useActions, useValues } from 'kea'
import { useState } from 'react'

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
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
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

function SlackSection(): JSX.Element {
    return (
        <SceneSection
            title="SupportHog Slack bot"
            description="Add the SupportHog bot to your Slack workspace to create and manage support tickets directly from Slack messages."
            className="mt-4"
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <SlackChannelSection />
            </LemonCard>
        </SceneSection>
    )
}

function SlackChannelSection(): JSX.Element {
    const {
        slackConnected,
        slackChannelId,
        slackChannels,
        slackChannelsLoading,
        slackTicketEmoji,
        slackTicketEmojiValue,
    } = useValues(supportSettingsLogic)
    const {
        connectSlack,
        setSlackChannel,
        loadSlackChannelsWithToken,
        setSlackTicketEmojiValue,
        saveSlackTicketEmoji,
        disconnectSlack,
    } = useActions(supportSettingsLogic)

    return (
        <div className="flex flex-col gap-y-2">
            <div>
                <label className="font-medium">Connection</label>
                <p className="text-xs text-muted-alt">
                    Install the SupportHog bot in your Slack workspace to enable support ticket creation from channels,
                    mentions, and emoji reactions. This is separate from the main PostHog Slack integration.
                </p>
                {!slackConnected && (
                    <LemonButton
                        className="mt-2"
                        type="primary"
                        size="small"
                        onClick={() => connectSlack(window.location.pathname)}
                    >
                        Add SupportHog to Slack
                    </LemonButton>
                )}
            </div>
            {slackConnected && (
                <>
                    <LemonDivider />
                    <div className="gap-4">
                        <div>
                            <label className="font-medium">Support channel</label>
                            <p className="text-xs text-muted-alt">
                                Messages posted in this channel will automatically create support tickets. Thread
                                replies become ticket messages.
                            </p>
                        </div>
                        <div className="flex gap-2 items-center">
                            <LemonSelect
                                value={slackChannelId}
                                options={[
                                    { value: null, label: 'None' },
                                    ...slackChannels.map((c: { id: string; name: string }) => ({
                                        value: c.id,
                                        label: `#${c.name}`,
                                    })),
                                ]}
                                onChange={(value) => {
                                    const channel = slackChannels.find((c: { id: string }) => c.id === value)
                                    setSlackChannel(value, channel?.name ?? null)
                                }}
                                loading={slackChannelsLoading}
                                placeholder="Select channel"
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={loadSlackChannelsWithToken}
                                disabledReason={slackChannelsLoading ? 'Loading channels...' : undefined}
                            >
                                Refresh
                            </LemonButton>
                        </div>
                    </div>
                    <LemonDivider />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Ticket emoji trigger</label>
                            <p className="text-xs text-muted-alt">
                                React with this emoji on any message to create a support ticket from it.
                            </p>
                        </div>
                        <div className="flex gap-2 items-center">
                            <LemonInput
                                value={slackTicketEmojiValue ?? slackTicketEmoji}
                                onChange={setSlackTicketEmojiValue}
                                placeholder="ticket"
                                className="max-w-[200px]"
                            />
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={saveSlackTicketEmoji}
                                disabledReason={!slackTicketEmojiValue ? 'Enter an emoji name' : undefined}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                    <LemonDivider />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Bot mention</label>
                            <p className="text-xs text-muted-alt">
                                Users can @mention the bot in any channel to create a support ticket.
                            </p>
                        </div>
                        <LemonTag type="success">Active</LemonTag>
                    </div>
                    <LemonDivider />
                    <div className="flex justify-end">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Remove SupportHog bot?',
                                    description:
                                        'This will stop creating tickets from Slack messages. Existing tickets will not be affected.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Remove',
                                        onClick: disconnectSlack,
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Remove SupportHog bot
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}

function EmailSection(): JSX.Element {
    return (
        <SceneSection
            title="Email channel"
            description="Receive support emails as conversation tickets. Customers email your support address, and replies from your team are sent back via email."
            className="mt-4"
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <EmailChannelSection />
            </LemonCard>
        </SceneSection>
    )
}

function EmailChannelSection(): JSX.Element {
    const {
        emailStatus,
        emailStatusLoading,
        emailFromAddress,
        emailFromName,
        emailConnecting,
        emailVerifying,
        emailTestSending,
    } = useValues(supportSettingsLogic)
    const { setEmailFromAddress, setEmailFromName, connectEmail, disconnectEmail, verifyEmailDomain, sendTestEmail } =
        useActions(supportSettingsLogic)

    const [testEmailAddress, setTestEmailAddress] = useState('')

    if (emailStatusLoading && !emailStatus) {
        return <div className="text-muted-alt text-sm">Loading email status...</div>
    }

    if (!emailStatus?.connected) {
        return (
            <div className="flex flex-col gap-y-2">
                <div>
                    <label className="font-medium">Connect email</label>
                    <p className="text-xs text-muted-alt">
                        Enter the email address customers will use to contact support. We'll provide forwarding
                        instructions and DNS records to set up.
                    </p>
                </div>
                <div className="flex flex-col gap-2 max-w-md">
                    <LemonInput
                        value={emailFromAddress}
                        onChange={setEmailFromAddress}
                        placeholder="support@company.com"
                        fullWidth
                    />
                    <LemonInput
                        value={emailFromName}
                        onChange={setEmailFromName}
                        placeholder="Acme Support"
                        fullWidth
                    />
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={connectEmail}
                        loading={emailConnecting}
                        disabledReason={
                            !emailFromAddress.trim()
                                ? 'Enter an email address'
                                : !emailFromName.trim()
                                  ? 'Enter a display name'
                                  : undefined
                        }
                    >
                        Connect email
                    </LemonButton>
                </div>
            </div>
        )
    }

    const sendingRecords = emailStatus.dns_records?.sending_dns_records || []

    return (
        <div className="flex flex-col gap-y-2">
            <div className="flex items-center gap-4 justify-between">
                <div>
                    <label className="font-medium">Connection</label>
                    <p className="text-xs text-muted-alt">Email channel is connected.</p>
                </div>
                <LemonTag type={emailStatus.domain_verified ? 'success' : 'warning'}>
                    {emailStatus.domain_verified ? 'Verified' : 'Pending verification'}
                </LemonTag>
            </div>

            <LemonDivider />

            <div>
                <label className="font-medium">Forwarding address</label>
                <p className="text-xs text-muted-alt mb-2">
                    Set up a forwarding rule in your email provider to forward emails from{' '}
                    <strong>{emailStatus.from_email}</strong> to this address:
                </p>
                <div className="flex gap-2 items-center">
                    <code className="bg-bg-light px-2 py-1 rounded text-sm flex-1 truncate">
                        {emailStatus.inbound_address}
                    </code>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => void copyToClipboard(emailStatus.inbound_address || '')}
                    >
                        Copy
                    </LemonButton>
                </div>
            </div>

            {sendingRecords.length > 0 && (
                <>
                    <LemonDivider />
                    <div>
                        <label className="font-medium">DNS records</label>
                        <p className="text-xs text-muted-alt mb-2">
                            Add these DNS records to your domain to authorize PostHog to send emails on behalf of{' '}
                            <strong>{emailStatus.domain}</strong>.
                        </p>
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                                <thead>
                                    <tr className="border-b">
                                        <th className="text-left py-1 pr-2 font-medium">Type</th>
                                        <th className="text-left py-1 pr-2 font-medium">Name</th>
                                        <th className="text-left py-1 pr-2 font-medium">Value</th>
                                        <th className="text-left py-1 font-medium">Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {sendingRecords.map(
                                        (
                                            record: {
                                                record_type: string
                                                name: string
                                                value: string
                                                valid: string
                                            },
                                            i: number
                                        ) => (
                                            <tr key={i} className="border-b">
                                                <td className="py-1 pr-2">
                                                    <code>{record.record_type}</code>
                                                </td>
                                                <td className="py-1 pr-2">
                                                    <code className="break-all">{record.name}</code>
                                                </td>
                                                <td className="py-1 pr-2">
                                                    <code className="break-all">{record.value}</code>
                                                </td>
                                                <td className="py-1">
                                                    <LemonTag
                                                        type={record.valid === 'valid' ? 'success' : 'muted'}
                                                        size="small"
                                                    >
                                                        {record.valid === 'valid' ? 'Valid' : 'Pending'}
                                                    </LemonTag>
                                                </td>
                                            </tr>
                                        )
                                    )}
                                </tbody>
                            </table>
                        </div>
                        <div className="mt-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={verifyEmailDomain}
                                loading={emailVerifying}
                            >
                                Verify domain
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}

            {emailStatus.domain_verified && (
                <>
                    <LemonDivider />
                    <div>
                        <label className="font-medium">Send test email</label>
                        <p className="text-xs text-muted-alt mb-2">
                            Send a test email to verify outbound delivery is working.
                        </p>
                        <div className="flex gap-2 max-w-md">
                            <LemonInput
                                value={testEmailAddress}
                                onChange={setTestEmailAddress}
                                placeholder="test@example.com"
                                fullWidth
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => sendTestEmail(testEmailAddress)}
                                loading={emailTestSending}
                                disabledReason={!testEmailAddress.trim() ? 'Enter an email address' : undefined}
                            >
                                Send test
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}

            <LemonDivider />
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Disconnect email?',
                            description:
                                'This will stop creating tickets from emails. Existing tickets will not be affected.',
                            primaryButton: {
                                status: 'danger',
                                children: 'Disconnect',
                                onClick: disconnectEmail,
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Disconnect email
                </LemonButton>
            </div>
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
                    <EmailSection />
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
