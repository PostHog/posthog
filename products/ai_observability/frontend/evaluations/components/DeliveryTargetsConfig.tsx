import { useValues } from 'kea'

import { IconLetter, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { IconSlack } from 'lib/lemon-ui/icons'

import type { ReportDestination } from '../evaluationReportLogic'

function DestinationRow({
    icon,
    title,
    onRemove,
    children,
}: {
    icon: JSX.Element
    title: string
    onRemove: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-semibold text-sm">
                    {icon}
                    {title}
                </span>
                <LemonButton
                    size="xsmall"
                    icon={<IconTrash />}
                    tooltip={`Remove ${title.toLowerCase()}`}
                    aria-label={`Remove ${title.toLowerCase()}`}
                    onClick={onRemove}
                />
            </div>
            {children}
        </div>
    )
}

/** Where reports go besides the Reports tab. Each destination is added from a menu, so unused ones take no room. */
export function DeliveryTargetsConfig({
    emailValue,
    onEmailChange,
    slackIntegrationId,
    onSlackIntegrationChange,
    slackChannelValue,
    onSlackChannelChange,
    shown,
    onAdd,
    onRemove,
}: {
    emailValue: string
    onEmailChange: (value: string) => void
    slackIntegrationId: number | null
    onSlackIntegrationChange: (value: number | null) => void
    slackChannelValue: string
    onSlackChannelChange: (value: string) => void
    shown: ReportDestination[]
    onAdd: (destination: ReportDestination) => void
    onRemove: (destination: ReportDestination) => void
}): JSX.Element {
    const { slackIntegrations, integrations } = useValues(integrationsLogic)
    const selectedIntegration =
        slackIntegrationId !== null ? integrations?.find((i) => i.id === slackIntegrationId) : undefined
    const showEmail = shown.includes('email')
    const showSlack = shown.includes('slack')
    const menuItems = [
        ...(showEmail ? [] : [{ label: 'Email', icon: <IconLetter />, onClick: () => onAdd('email') }]),
        ...(showSlack ? [] : [{ label: 'Slack', icon: <IconSlack />, onClick: () => onAdd('slack') }]),
    ]

    return (
        <div className="space-y-2">
            <div>
                <label className="font-semibold text-sm">Destinations</label>
                <p className="text-xs text-muted mb-0">Reports always show in the Reports tab. Also send them to:</p>
            </div>
            <div className="grid grid-cols-1 items-start gap-2 @min-[48rem]/evaluation:grid-cols-2">
                {showEmail && (
                    <DestinationRow icon={<IconLetter />} title="Email" onRemove={() => onRemove('email')}>
                        <LemonInput
                            value={emailValue}
                            onChange={onEmailChange}
                            placeholder="email1@example.com, email2@example.com"
                            fullWidth
                        />
                        <p className="text-xs text-muted mb-0">Comma-separated email addresses</p>
                    </DestinationRow>
                )}
                {showSlack && (
                    <DestinationRow icon={<IconSlack />} title="Slack" onRemove={() => onRemove('slack')}>
                        {!slackIntegrations?.length ? (
                            <SlackNotConfiguredBanner />
                        ) : (
                            <div className="space-y-2">
                                <IntegrationChoice
                                    integration="slack"
                                    value={slackIntegrationId ?? undefined}
                                    onChange={(newValue) => {
                                        if (newValue !== slackIntegrationId) {
                                            onSlackChannelChange('')
                                        }
                                        onSlackIntegrationChange(newValue)
                                    }}
                                />
                                {selectedIntegration && (
                                    <SlackChannelPicker
                                        value={slackChannelValue}
                                        onChange={(val) => onSlackChannelChange(val || '')}
                                        integration={selectedIntegration}
                                    />
                                )}
                            </div>
                        )}
                    </DestinationRow>
                )}
            </div>
            {menuItems.length > 0 && (
                <LemonMenu items={menuItems}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        data-attr="llma-evaluation-report-add-destination"
                    >
                        Add destination
                    </LemonButton>
                </LemonMenu>
            )}
        </div>
    )
}
