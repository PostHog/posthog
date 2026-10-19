import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { formatReportMetricValue } from 'products/signals/frontend/inbox/utils/reportMetrics'

import { reportSourceLine, reportTitle } from './todaySignalReports'

export interface TodayReportPreview {
    sources: string | null
    lead: string | null
    metric: { title: string; value: string } | null
    pullRequest: { url: string; state: string | null } | null
}

type PreviewMetric = Pick<ReportMetricApi, 'title' | 'unit' | 'value_format'> & { value?: number | null }

function previewMetric(metrics: PreviewMetric[] | undefined): TodayReportPreview['metric'] {
    for (const metric of metrics ?? []) {
        const value = formatReportMetricValue(metric, metric.value)
        if (value) {
            return { title: metric.title, value }
        }
    }
    return null
}

function comparable(text: string): string {
    return text.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, '')
}

function distinctLead(lead: string | null | undefined, title: string): string | null {
    const text = lead?.trim()
    return text && comparable(text) !== comparable(title) ? text : null
}

function worthShowing(preview: TodayReportPreview): TodayReportPreview | null {
    return preview.lead || preview.metric || preview.pullRequest ? preview : null
}

export function reportPreview(report: SignalReport): TodayReportPreview | null {
    return worthShowing({
        sources: report.source_products?.length || report.scout_name ? reportSourceLine(report).line : null,
        lead: distinctLead(report.summary_lead, reportTitle(report)),
        metric: previewMetric(report.metrics),
        pullRequest: report.implementation_pr_url
            ? {
                  url: report.implementation_pr_url,
                  state: report.implementation_pr_merged ? 'merged' : (report.implementation_pr_state ?? null),
              }
            : null,
    })
}
