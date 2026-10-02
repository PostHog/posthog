import { Text } from '@posthog/quill'

import { Sparkline } from 'lib/components/Sparkline'

import { ReportChart } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayReportSections, todayReportImpact } from './todayReportPresentation'
import { TodayReportProse } from './TodayReportProse'

export function TodayReportImpact({
    report,
    sections,
}: {
    report: SignalReport
    sections: TodayReportSections
}): JSX.Element {
    const impact = todayReportImpact(report)
    const series = impact?.metric.series?.filter((point) => Number.isFinite(point)) ?? []
    const firstChart = !impact ? report.charts?.[0] : undefined

    if (!impact) {
        return (
            <section className="flex flex-col gap-4" data-attr="today-report-impact">
                {sections.lead ? (
                    <TodayReportProse markdown={sections.lead} tone="hero" />
                ) : (
                    <Text render={<p />} className="text-xl leading-snug font-medium">
                        No summary yet. An agent is still investigating.
                    </Text>
                )}
                {firstChart && <ReportChart chartId={firstChart.chart_id} />}
            </section>
        )
    }

    return (
        <section className="flex flex-col gap-4" data-attr="today-report-impact">
            <div className="flex flex-col gap-3">
                <Text render={<p />} className="text-xl leading-snug text-pretty text-muted-foreground">
                    <span translate="no" className="font-semibold text-foreground">
                        {impact.value}
                    </span>
                    <span>{` ${impact.text}`}</span>
                </Text>
                {series.length > 1 && (
                    <Sparkline
                        data={series}
                        type="line"
                        color="data-color-1"
                        name={impact.metric.title}
                        className="h-8 w-full"
                    />
                )}
            </div>
            {sections.lead && <TodayReportProse markdown={sections.lead} tone="body" />}
        </section>
    )
}
