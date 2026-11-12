import { IconAtSign, IconCheck, IconClock, IconEye } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'

import type { EvaluationReportDestinationApi } from '../../generated/api.schemas'
import type { EvaluationReportRun } from '../types'

// The logo keeps its shape but takes the text color, so it reads as quietly as the email icon.
const SLACK_ICON_CLASS = '[&_path]:fill-current'

function DestinationIcon({ destination }: { destination: EvaluationReportDestinationApi }): JSX.Element {
    return destination.type === 'slack' ? <IconSlack className={SLACK_ICON_CLASS} /> : <IconAtSign />
}

function destinationLabel({ type, name }: EvaluationReportDestinationApi): string {
    return type === 'slack' && !name.startsWith('#') ? `#${name}` : name
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
    const labels = destinations.map(destinationLabel)
    const hasSlack = destinations.some((destination) => destination.type === 'slack')
    const hasEmail = destinations.some((destination) => destination.type === 'email')
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Sent to</span>
                    {destinations.map((destination, index) => (
                        <span key={index} className="flex items-center gap-1.5">
                            <DestinationIcon destination={destination} />
                            {labels[index]}
                        </span>
                    ))}
                </div>
            }
        >
            <span
                className="inline-flex items-center gap-1.5 text-base text-secondary"
                aria-label={`Sent to ${labels.join(', ')}`}
            >
                {hasSlack && <IconSlack className={SLACK_ICON_CLASS} />}
                {hasEmail && <IconAtSign />}
            </span>
        </Tooltip>
    )
}
