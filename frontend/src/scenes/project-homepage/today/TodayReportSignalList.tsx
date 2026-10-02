import { useState } from 'react'

import { Button } from '@posthog/quill'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { TodayReportSignalRow } from './TodayReportSignalRow'

const SHOWN_SIGNAL_COUNT = 6

export function TodayReportSignalList({
    reportId,
    signals,
    showIcon,
}: {
    reportId: string
    signals: SignalNodeApi[]
    showIcon: boolean
}): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const shown = showAll ? signals : signals.slice(0, SHOWN_SIGNAL_COUNT)
    const hidden = signals.length - shown.length

    return (
        <div className="flex flex-col divide-y divide-border">
            {shown.map((signal) => (
                <TodayReportSignalRow key={signal.signal_id} reportId={reportId} signal={signal} showIcon={showIcon} />
            ))}
            {hidden > 0 && (
                <Button
                    variant="link-muted"
                    size="sm"
                    className="self-start"
                    onClick={() => setShowAll(true)}
                    data-attr="today-report-signals-show-more"
                >
                    {`Show ${hidden} more`}
                </Button>
            )}
        </div>
    )
}
