import { SignalReport } from 'products/signals/frontend/inbox/types'
import {
    formatReportMetricValue,
    selectReportCardImpactMetric,
} from 'products/signals/frontend/inbox/utils/reportMetrics'

import type { TodayReportPreview } from './todayReportPreviews'

export interface TodayFeedReportFacts {
    figure: { value: string; label: string } | null
    series: number[] | null
    pullRequest: { url: string; state: string; number: string | null } | null
    prompt: string | null
}

function reportFigure(report: SignalReport): Pick<TodayFeedReportFacts, 'figure' | 'series'> {
    const metric = selectReportCardImpactMetric(report.metrics)
    const value = metric && formatReportMetricValue(metric, metric.value)
    return {
        figure: value ? { value, label: metric.title } : null,
        series: metric?.series ?? null,
    }
}

function reportPullRequest(
    title: string,
    preview: TodayReportPreview | undefined
): TodayFeedReportFacts['pullRequest'] {
    const pullRequest = preview?.pullRequest
    if (!pullRequest) {
        return null
    }
    const number = pullRequest.url.match(/\/pull\/(\d+)/)?.[1] ?? null
    return number && title.includes(`#${number}`)
        ? null
        : { url: pullRequest.url, state: pullRequest.state ?? 'open', number }
}

export function feedReportFacts(
    report: SignalReport,
    title: string,
    preview: TodayReportPreview | undefined,
    done: boolean
): TodayFeedReportFacts {
    return {
        ...reportFigure(report),
        pullRequest: reportPullRequest(title, preview),
        prompt: done ? null : (report.suggested_prompts?.[0] ?? null),
    }
}
