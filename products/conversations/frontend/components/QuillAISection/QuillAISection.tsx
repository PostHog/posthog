import { useId } from 'react'

import {
    Button,
    Card,
    CardContent,
    Checkbox,
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import {
    CHANNEL_LABELS,
    PUBLISHABLE_TICKET_TYPES,
    REPLY_MODE_OPTIONS,
    TICKET_TYPES,
} from '../../scenes/settings/aiAgentSettingsOptions'
import { aiTriageTicketTypeLabel, TicketChannel } from '../../types'
import { AIContextAccountPropertiesSection } from '../AIContextAccountPropertiesSection/AIContextAccountPropertiesSection'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillSettingsSwitchRow } from '../QuillSettingsSwitchRow/QuillSettingsSwitchRow'
import { SupportPlaybookSection } from '../SupportPlaybookSection/SupportPlaybookSection'

type ReplyMode = (typeof REPLY_MODE_OPTIONS)[number]['value']

export function QuillAISection({
    aiSuggestionsEnabled,
    aiSuggestionsLoading,
    aiDiagnosticsEnabled,
    aiDiagnosticsLoading,
    aiAllChannels,
    aiResolutionChannels,
    aiReplyModes,
    isChannelActive,
    onAiSuggestionsEnabledChange,
    onAiDiagnosticsEnabledChange,
    onResolutionChannelToggle,
    onReplyModeChange,
    onOpenChannelSettings,
}: {
    aiSuggestionsEnabled: boolean
    aiSuggestionsLoading: boolean
    aiDiagnosticsEnabled: boolean
    aiDiagnosticsLoading: boolean
    aiAllChannels: TicketChannel[]
    aiResolutionChannels: TicketChannel[]
    aiReplyModes: Record<string, Record<string, ReplyMode>>
    isChannelActive: (channel: TicketChannel) => boolean
    onAiSuggestionsEnabledChange: (checked: boolean) => void
    onAiDiagnosticsEnabledChange: (checked: boolean) => void
    onResolutionChannelToggle: (channel: TicketChannel, checked: boolean) => void
    onReplyModeChange: (channel: string, ticketType: string, mode: ReplyMode) => void
    onOpenChannelSettings: (channel: TicketChannel) => void
}): JSX.Element {
    const idPrefix = useId()

    return (
        <div className="flex flex-col gap-6">
            <QuillSettingsSubsection
                title="AI agent"
                description="When enabled, the AI agent automatically generates reply suggestions as private notes when new tickets arrive. Replies are grounded in your business knowledge sources."
            >
                <Card size="sm" className="max-w-200">
                    <CardContent>
                        <QuillSettingsSwitchRow
                            label="Enable AI agent"
                            description="Requires AI data processing consent at the organization level and at least one ready business knowledge source."
                            checked={aiSuggestionsEnabled}
                            onCheckedChange={onAiSuggestionsEnabledChange}
                            loading={aiSuggestionsLoading}
                        />
                    </CardContent>
                </Card>
            </QuillSettingsSubsection>

            {aiSuggestionsEnabled && (
                <QuillSettingsSubsection
                    title="Investigate ticket data"
                    description="When enabled, tickets that report something broken let the agent query your project's data — events, error tracking, session recordings, and logs — to investigate the issue instead of relying on documentation alone. The agent has read-only access scoped to your project."
                >
                    <Card size="sm" className="max-w-200">
                        <CardContent>
                            <QuillSettingsSwitchRow
                                label="Allow the agent to investigate ticket data"
                                description="Leave this off to keep the agent grounded only in documentation and your business knowledge."
                                checked={aiDiagnosticsEnabled}
                                onCheckedChange={onAiDiagnosticsEnabledChange}
                                loading={aiDiagnosticsLoading}
                            />
                        </CardContent>
                    </Card>
                </QuillSettingsSubsection>
            )}

            {aiSuggestionsEnabled && <SupportPlaybookSection />}
            {aiSuggestionsEnabled && <AIContextAccountPropertiesSection />}

            {aiSuggestionsEnabled && (
                <QuillSettingsSubsection
                    title="Allowed channels"
                    description="Choose which channels the AI agent runs on. Inactive channels must be enabled under Channels first."
                >
                    <Card size="sm" className="max-w-200">
                        <CardContent className="flex flex-col gap-2">
                            {aiAllChannels.map((channel) => {
                                const active = isChannelActive(channel)
                                const checkboxId = `${idPrefix}-${channel}`

                                return (
                                    <Field key={channel} orientation="horizontal">
                                        <Checkbox
                                            id={checkboxId}
                                            checked={active && aiResolutionChannels.includes(channel)}
                                            disabledReason={
                                                active ? undefined : 'Enable this channel in Channels settings first'
                                            }
                                            onCheckedChange={(checked) => onResolutionChannelToggle(channel, checked)}
                                        />
                                        <FieldLabel htmlFor={checkboxId} className="flex-wrap gap-x-1">
                                            {CHANNEL_LABELS[channel]}
                                            {!active && (
                                                <>
                                                    <span className="text-muted-foreground">·</span>
                                                    <Button
                                                        variant="link"
                                                        size="inline"
                                                        nativeButton={false}
                                                        render={
                                                            <LinkPrimitive
                                                                to={urls.supportSettings()}
                                                                onClick={(e) => {
                                                                    e.preventDefault()
                                                                    onOpenChannelSettings(channel)
                                                                }}
                                                            />
                                                        }
                                                    >
                                                        Enable in Channels first
                                                    </Button>
                                                </>
                                            )}
                                        </FieldLabel>
                                    </Field>
                                )
                            })}
                        </CardContent>
                    </Card>
                </QuillSettingsSubsection>
            )}

            {aiSuggestionsEnabled && aiResolutionChannels.length > 0 && (
                <QuillSettingsSubsection
                    title="Reply behavior"
                    description={
                        <>
                            For each channel and ticket type, choose whether the AI agent posts a private note (visible
                            only to your team) or sends a safety-reviewed reply directly to the customer. On channels
                            set to AI reply, the agent may also ask the customer one clarifying question.{' '}
                            <strong>Diagnostic</strong> and <strong>Account/Billing</strong> replies may include data
                            from your project, so they're always kept as private notes and can't be sent directly to the
                            customer.
                        </>
                    }
                >
                    <Card size="sm" flush className="max-w-200">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Channel</TableHead>
                                    {TICKET_TYPES.map((tt) => (
                                        <TableHead key={tt}>{aiTriageTicketTypeLabel[tt]}</TableHead>
                                    ))}
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {aiResolutionChannels.map((channel) => (
                                    <TableRow key={channel}>
                                        <TableCell className="font-medium">
                                            {CHANNEL_LABELS[channel] ?? channel}
                                        </TableCell>
                                        {TICKET_TYPES.map((tt) =>
                                            PUBLISHABLE_TICKET_TYPES.has(tt) ? (
                                                <TableCell key={tt}>
                                                    <Select<ReplyMode>
                                                        items={REPLY_MODE_OPTIONS}
                                                        value={aiReplyModes[channel]?.[tt] ?? 'private_note'}
                                                        onValueChange={(value) => {
                                                            if (value) {
                                                                onReplyModeChange(channel, tt, value)
                                                            }
                                                        }}
                                                    >
                                                        <SelectTrigger
                                                            size="sm"
                                                            aria-label={`${CHANNEL_LABELS[channel] ?? channel} ${aiTriageTicketTypeLabel[tt]}`}
                                                        >
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            {REPLY_MODE_OPTIONS.map((option) => (
                                                                <SelectItem key={option.value} value={option.value}>
                                                                    {option.label}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                </TableCell>
                                            ) : (
                                                <TableCell key={tt}>
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        Private note
                                                    </Text>
                                                </TableCell>
                                            )
                                        )}
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </Card>
                </QuillSettingsSubsection>
            )}
        </div>
    )
}
