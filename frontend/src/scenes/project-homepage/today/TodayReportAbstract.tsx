import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayFigureMark } from './TodayFigureMark'
import { TodayInlineMarkdown } from './TodayInlineMarkdown'
import { TodayInlineTrend } from './TodayInlineTrend'
import { todayReportLogic } from './todayReportLogic'

export function TodayReportAbstract({ report }: { report: SignalReport }): JSX.Element | null {
    const {
        impactNumbers: numbers,
        impactText,
        leadStatesNumber,
    } = useValues(todayReportLogic({ reportId: report.id }))

    if (numbers.length === 0 && !impactText) {
        if (leadStatesNumber) {
            return null
        }
        return (
            <Text size="sm" variant="muted" render={<p />} data-attr="today-report-abstract">
                The report doesn’t say how big this is yet.
            </Text>
        )
    }

    if (numbers.length === 0) {
        return (
            <Text size="sm" render={<p />} className="leading-relaxed text-pretty" data-attr="today-report-abstract">
                <TodayInlineMarkdown markdown={impactText} />
            </Text>
        )
    }

    return (
        <ul className="m-0 flex list-none flex-col gap-3 p-0" aria-label="Impact" data-attr="today-report-abstract">
            {numbers.map((number, index) => (
                <li key={number.key} className="flex flex-col gap-0.5">
                    <Text size="sm" render={<span />} className="text-pretty">
                        <TodayFigureMark
                            figure={number.value}
                            content={number.content}
                            reportId={report.id}
                            order={index}
                        >
                            <span translate="no" className="tabular-nums">
                                {number.value}
                            </span>
                        </TodayFigureMark>
                        <span>{` ${number.label}`}</span>
                    </Text>
                    {number.window && (
                        <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-2">
                            <span>{number.window}</span>
                            {number.chart && (
                                <TodayInlineTrend
                                    values={number.chart.data}
                                    type={number.chart.type}
                                    partialLast={number.chart.partialLast}
                                />
                            )}
                        </Text>
                    )}
                </li>
            ))}
        </ul>
    )
}
