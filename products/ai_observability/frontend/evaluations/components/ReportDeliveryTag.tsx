import { IconAtSign, IconCheck, IconClock, IconEye } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'

import type { EvaluationReportRun } from '../types'

// The logo keeps its shape but takes the text color, so it reads as quietly as the email icon.
const SLACK_ICON_CLASS = '[&_path]:fill-current'

function DestinationIcon({ destination }: { destination: string }): JSX.Element {
    // Delivery stores Slack channels with a leading "#" and email addresses as they are.
    return destination.startsWith('#') ? <IconSlack className={SLACK_ICON_CLASS} /> : <IconAtSign />
}

function StatusIcon({ icon, tooltip }: { icon: JSX.Element; tooltip: string }): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <span className="inline-flex text-base text-secondary" aria-label={tooltip}>
                {icon}
            </span>
        </Tooltip>
    )
}

/** Problems get a labeled tag; a sent report shows where it went as icons, with the details on hover. */
export function ReportDeliveryTag({
    run,
}: {
    run: Pick<EvaluationReportRun, 'delivery_status' | 'delivery_destinations'>
}): JSX.Element {
    const destinations = run.delivery_destinations ?? []

    switch (run.delivery_status) {
        case 'failed':
            return (
                <LemonTag type="danger" size="small">
                    Failed
                </LemonTag>
            )
        case 'partial_failure':
            return (
                <LemonTag type="warning" size="small">
                    Partial failure
                </LemonTag>
            )
        case 'pending':
            return <StatusIcon icon={<IconClock />} tooltip="Sending" />
        case 'generated':
            return <StatusIcon icon={<IconEye />} tooltip="Not sent anywhere. Shown only here." />
    }

    if (destinations.length === 0) {
        return <StatusIcon icon={<IconCheck />} tooltip="Delivered" />
    }
    const hasSlack = destinations.some((destination) => destination.startsWith('#'))
    const hasEmail = destinations.some((destination) => !destination.startsWith('#'))
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Sent to</span>
                    {destinations.map((destination) => (
                        <span key={destination} className="flex items-center gap-1.5">
                            <DestinationIcon destination={destination} />
                            {destination}
                        </span>
                    ))}
                </div>
            }
        >
            <span
                className="inline-flex items-center gap-1.5 text-base text-secondary"
                aria-label={`Sent to ${destinations.join(', ')}`}
            >
                {hasSlack && <IconSlack className={SLACK_ICON_CLASS} />}
                {hasEmail && <IconAtSign />}
            </span>
        </Tooltip>
    )
}
