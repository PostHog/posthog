import { IconChevronDown, IconCopy } from '@posthog/icons'
import { LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { parseCommaSeparatedSlackTargetDisplayLabels } from 'lib/utils/slackChannelValue'

import { TargetTypeEnumApi, type SubscriptionApi } from '~/generated/core/api.schemas'

function parseEmailRecipients(targetValue: string): string[] {
    return targetValue
        .split(',')
        .map((e) => e.trim())
        .filter(Boolean)
}

function truncateWebhookUrl(url: string): string {
    if (url.length > 48) {
        return `${url.slice(0, 24)}…${url.slice(-12)}`
    }
    return url
}

function DestinationListCell({ parts, copyDescription }: { parts: string[]; copyDescription: string }): JSX.Element {
    if (parts.length === 0) {
        return <span className="text-secondary">—</span>
    }

    if (parts.length === 1) {
        return (
            <span className="text-secondary max-w-xl truncate block" title={parts[0]}>
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description={copyDescription}
                    style={{ justifyContent: 'flex-end' }}
                >
                    {parts[0]}
                </CopyToClipboardInline>
            </span>
        )
    }

    return (
        <span className="text-secondary inline-flex items-center gap-x-1 min-w-0 max-w-xl flex-wrap">
            <span className="min-w-0 truncate" title={parts[0]} data-attr="subscription-destination-primary">
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description={copyDescription}
                    style={{ justifyContent: 'flex-end' }}
                >
                    {parts[0]}
                </CopyToClipboardInline>
            </span>
            <LemonMenu
                placement="bottom-start"
                items={parts.slice(1).map((part) => ({
                    label: part,
                    sideIcon: <IconCopy className="text-primary-3000" />,
                    onClick: () => copyToClipboard(part, copyDescription),
                }))}
            >
                <LemonTag type="primary" className="inline-flex">
                    <span>+{parts.length - 1}</span>
                    <IconChevronDown className="w-4 h-4" />
                </LemonTag>
            </LemonMenu>
        </span>
    )
}

export function SubscriptionDestinationCell({ sub }: { sub: SubscriptionApi }): JSX.Element {
    if (sub.target_type === TargetTypeEnumApi.Email) {
        const emails = parseEmailRecipients(sub.target_value)
        return <DestinationListCell parts={emails} copyDescription="email recipient" />
    }

    if (sub.target_type === TargetTypeEnumApi.Slack) {
        const parts = parseCommaSeparatedSlackTargetDisplayLabels(sub.target_value)
        return <DestinationListCell parts={parts} copyDescription="Slack destination" />
    }

    const text = truncateWebhookUrl(sub.target_value)
    return (
        <span className="text-secondary max-w-md truncate block" title={sub.target_value}>
            {text}
        </span>
    )
}
