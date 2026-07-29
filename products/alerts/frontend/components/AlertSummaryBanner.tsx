import { ReactNode } from 'react'

import { AlertSummaryParts } from './alertSummary'

export type AlertSummarySection = 'monitor' | 'schedule' | 'notify'

export function AlertSummaryBanner({
    summary,
    header,
    footer,
    activeSection,
}: {
    summary: AlertSummaryParts
    header?: ReactNode
    footer?: ReactNode
    activeSection?: AlertSummarySection
}): JSX.Element {
    const fires = summary.fires || 'a threshold'
    const cadence = summary.cadence || 'unscheduled'
    const notifies = summary.notifies || 'no one'

    return (
        <div className="w-full rounded border border-border bg-bg-light px-3 py-2 text-sm space-y-2">
            {header}
            <dl className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <SummarySection
                    active={activeSection === 'monitor'}
                    dataAttr="alert-summary-monitor"
                    label="Fires when"
                    value={fires}
                />
                <SummarySection
                    active={activeSection === 'schedule'}
                    dataAttr="alert-summary-schedule"
                    label="runs"
                    value={cadence}
                    separated
                />
                <SummarySection
                    active={activeSection === 'notify'}
                    dataAttr="alert-summary-notify"
                    label="notifies"
                    value={notifies}
                    separated
                />
            </dl>
            {footer ? <div className="flex text-muted">{footer}</div> : null}
        </div>
    )
}

function SummarySection({
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
            className={`flex items-center gap-3 ${separated ? "before:text-border before:content-['·']" : ''}`}
            data-attr={dataAttr}
        >
            <dt className={active ? 'font-bold text-primary' : 'text-muted'}>{label}</dt>
            <dd
                className={
                    active
                        ? 'font-medium underline decoration-dotted decoration-border underline-offset-4'
                        : 'font-medium'
                }
            >
                {value}
            </dd>
        </div>
    )
}
