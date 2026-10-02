import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { ReportCardSparkline } from 'products/signals/frontend/inbox/components/cards/ReportCardSparkline'

import { TodayIcon } from './TodayIcon'
import { TodaySignalGroup, signalHeadline } from './todayReportPresentation'
import { TodayReportSignalList } from './TodayReportSignalList'
import { sourceStyle } from './todaySignalReports'

export function TodayReportSignalGroup({
    reportId,
    group,
}: {
    reportId: string
    group: TodaySignalGroup
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const source = sourceStyle(group.source)
    const newest = group.signals[0]
    const oldest = group.signals[group.signals.length - 1]
    const range = dayjs(newest.timestamp).isSame(oldest.timestamp, 'day')
        ? dayjs(newest.timestamp).format('D MMM')
        : `${dayjs(oldest.timestamp).format('D MMM')} – ${dayjs(newest.timestamp).format('D MMM')}`

    return (
        <div>
            <Item
                variant="default"
                size="sm"
                render={<button type="button" aria-expanded={open} />}
                onClick={() => setOpen(!open)}
                className="group/row text-left text-foreground no-underline hover:bg-fill-hover"
                data-attr="today-report-signal-group"
            >
                <ItemMedia variant="icon" className="text-muted-foreground">
                    <TodayIcon icon={source.icon} />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemTitle className="line-clamp-2 font-normal">
                        {open ? source.label : signalHeadline(newest)}
                    </ItemTitle>
                    <ItemDescription>
                        {open
                            ? pluralize(group.signals.length, 'signal')
                            : `${source.label} · ${pluralize(group.signals.length, 'signal')}`}
                    </ItemDescription>
                </ItemContent>
                <ItemActions className="shrink-0">
                    {group.buckets.length ? (
                        <ReportCardSparkline values={group.buckets} type="bar" />
                    ) : (
                        <Text size="xs" variant="muted" className="tabular-nums">
                            {range}
                        </Text>
                    )}
                    <IconChevronDown
                        className={cn('size-3.5 text-muted-foreground transition-transform', open && 'rotate-180')}
                    />
                </ItemActions>
            </Item>
            {open && (
                <div className="ps-8">
                    <TodayReportSignalList reportId={reportId} signals={group.signals} showIcon={false} />
                </div>
            )}
        </div>
    )
}
