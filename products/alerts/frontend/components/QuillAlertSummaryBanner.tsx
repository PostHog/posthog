import { ReactNode } from 'react'

import { Card, CardContent, cn } from '@posthog/quill'

import { AlertSummaryParts } from './alertSummary'
import { AlertSummarySection } from './AlertSummaryBanner'

export function QuillAlertSummaryBanner({
    summary,
    header,
    footer,
    activeSection,
    showCadence = true,
}: {
    summary: AlertSummaryParts
    header?: ReactNode
    footer?: ReactNode
    activeSection?: AlertSummarySection
    showCadence?: boolean
}): JSX.Element {
    const fires = summary.fires || 'a threshold'
    const cadence = summary.cadence || 'unscheduled'
    const notifies = summary.notifies || 'no one'

    return (
        <Card size="sm" className="w-full">
            <CardContent className="flex flex-col gap-2 text-xs">
                {header}
                <dl className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <QuillSummarySection
                        active={activeSection === 'monitor'}
                        dataAttr="alert-summary-monitor"
                        label="Fires when"
                        value={fires}
                    />
                    {showCadence ? (
                        <QuillSummarySection
                            active={activeSection === 'schedule'}
                            dataAttr="alert-summary-schedule"
                            label="runs"
                            value={cadence}
                            separated
                        />
                    ) : null}
                    {summary.filters ? (
                        <QuillSummarySection
                            active={activeSection === 'monitor'}
                            dataAttr="alert-summary-filters"
                            label="matching"
                            value={summary.filters}
                            separated
                        />
                    ) : null}
                    <QuillSummarySection
                        active={activeSection === 'notify'}
                        dataAttr="alert-summary-notify"
                        label="notifies"
                        value={notifies}
                        separated
                    />
                </dl>
                {footer ? <div className="flex text-muted-foreground">{footer}</div> : null}
            </CardContent>
        </Card>
    )
}

function QuillSummarySection({
    active,
    dataAttr,
    label,
    value,
    separated = false,
}: {
    active: boolean
    dataAttr: string
    label: string
    value: string
    separated?: boolean
}): JSX.Element {
    return (
        <div
            className={cn('flex items-center gap-3', separated && "before:text-subtle-foreground before:content-['·']")}
            data-attr={dataAttr}
        >
            <dt className={active ? 'font-semibold text-primary' : 'text-muted-foreground'}>{label}</dt>
            <dd
                className={cn(
                    'm-0 font-medium',
                    active && 'underline decoration-border decoration-dotted underline-offset-4'
                )}
            >
                {value}
            </dd>
        </div>
    )
}
