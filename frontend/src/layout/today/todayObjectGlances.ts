import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { baseObjectType } from 'scenes/library/libraryUtils'
import { todayNumber } from 'scenes/project-homepage/today/todayNumbers'

import type { Noun } from '~/models/groupsModel'
import type { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { type Experiment, ExperimentStatus, type FeatureFlagConfig } from '~/types'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import type { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'
import { dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import type { DashboardApi } from 'products/dashboards/frontend/generated/api.schemas'
import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'
import { experimentsRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentApi } from 'products/experiments/frontend/generated/api.schemas'
import {
    isRulesV2FeatureFlagConfig,
    isV1FeatureFlagConfig,
} from 'products/feature_flags/frontend/featureFlagConfigFormat'
import { featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'
import { insightsList } from 'products/product_analytics/frontend/generated/api'
import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'
import { surveysRetrieve } from 'products/surveys/frontend/generated/api'
import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import { activityDetail } from './todayWorkItems'

export interface TodayObjectGlance {
    status?: { label: string; tone: 'success' | 'warning' | 'info' | 'default' }
    headline?: {
        value: string
        caption: string
        series: number[]
        labels: string[]
        formatValue?: (value: number) => string
    }
    description?: string
    facts: [string, string][]
}

export type TodayAggregationLabel = (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun

export interface TodayGlanceFormat {
    currency: CurrencyCode
    aggregationLabel: TodayAggregationLabel
}

export const GLANCE_TYPES = ['insight', 'feature_flag', 'experiment', 'survey', 'cohort', 'dashboard']

const since = (timestamp: string | null | undefined): string | null => activityDetail(timestamp ?? null)?.text ?? null

const day = (timestamp: string): string => dayjs(timestamp).format('D MMM YYYY')

function facts(entries: [string, string | null | undefined][]): [string, string][] {
    return entries.filter((entry): entry is [string, string] => !!entry[1])
}

function running(start: string | null | undefined): TodayObjectGlance['status'] {
    return {
        label: start ? `Running for ${pluralize(Math.max(1, dayjs().diff(start, 'day')), 'day')}` : 'Running',
        tone: 'success',
    }
}

function lifecycle(start: string | null | undefined, end: string | null | undefined): TodayObjectGlance['status'] {
    if (!start) {
        return { label: 'Draft', tone: 'default' }
    }
    if (end) {
        return { label: 'Complete', tone: 'default' }
    }
    return running(start)
}

function experimentStatus(experiment: ExperimentApi): TodayObjectGlance['status'] {
    switch (getExperimentStatus(experiment as Pick<Experiment, 'status' | 'start_date' | 'end_date'>)) {
        case ExperimentStatus.Running:
            return running(experiment.start_date)
        case ExperimentStatus.Paused:
            return { label: 'Paused', tone: 'warning' }
        case ExperimentStatus.ExposureFrozen:
            return { label: 'Exposure frozen', tone: 'info' }
        case ExperimentStatus.Stopped:
            return { label: 'Complete', tone: 'default' }
        case ExperimentStatus.Draft:
            return { label: 'Draft', tone: 'default' }
    }
}

interface TrendSeries {
    data: number[]
    labels?: string[]
    label?: string
}

interface FunnelStep {
    count: number
    compare_label?: string
}

function insightFormatter(insight: InsightApi, currency: CurrencyCode): (value: number) => string {
    const query = insight.query as Record<string, any> | null | undefined
    const trendsFilter: TrendsFilter | undefined =
        isInsightVizNode(query) && isTrendsQuery(query.source) ? (query.source.trendsFilter ?? undefined) : undefined
    const hasFormat =
        !!trendsFilter &&
        (!!trendsFilter.aggregationAxisFormat ||
            !!trendsFilter.aggregationAxisPrefix ||
            !!trendsFilter.aggregationAxisPostfix ||
            trendsFilter.decimalPlaces != null ||
            trendsFilter.minDecimalPlaces != null)
    return hasFormat ? (value) => formatAggregationAxisValue(trendsFilter, value, currency) : todayNumber
}

function insightHeadline(result: unknown, formatValue: (value: number) => string): TodayObjectGlance['headline'] {
    if (!Array.isArray(result) || result.length === 0) {
        return undefined
    }
    const series = result.find((entry: TrendSeries) => Array.isArray(entry?.data) && entry.data.length > 0) as
        | TrendSeries
        | undefined
    if (series) {
        const values = series.data.slice(-30)
        return {
            value: formatValue(values[values.length - 1]),
            caption: series.label ?? '',
            series: values,
            labels: (series.labels ?? []).slice(-30),
            formatValue,
        }
    }
    if (result.some((entry: TrendSeries) => Array.isArray(entry?.data))) {
        return undefined
    }
    const steps = ((Array.isArray(result[0]) ? result[0] : result) as FunnelStep[]).filter(
        (step) => step.compare_label !== 'previous'
    )
    const [top, bottom] = [steps[0]?.count, steps[steps.length - 1]?.count]
    return top && steps.length > 1 && bottom !== undefined
        ? { value: `${Math.round((bottom / top) * 100)}%`, caption: 'conversion', series: [], labels: [] }
        : undefined
}

export function insightGlance(insight: InsightApi, currency: CurrencyCode): TodayObjectGlance {
    return {
        headline: insightHeadline(insight.result, insightFormatter(insight, currency)),
        description: insight.description || undefined,
        facts: facts([
            ['Refreshed', since(insight.last_refresh)],
            ['Edited by', insight.last_modified_by?.first_name],
        ]),
    }
}

export function flagRollout(
    filters: FeatureFlagApi['filters'],
    aggregationLabel: TodayAggregationLabel
): string | null {
    const config = (filters ?? {}) as unknown as FeatureFlagConfig
    if (isRulesV2FeatureFlagConfig(config)) {
        return pluralize(config.rules.length, 'rule')
    }
    if (!isV1FeatureFlagConfig(config)) {
        return null
    }
    const variants = config.multivariate?.variants ?? []
    if (variants.length > 0) {
        return pluralize(variants.length, 'variant')
    }
    const groups = config.groups ?? []
    if (groups.length === 1 && !groups[0].properties?.length) {
        const population = aggregationLabel(config.aggregation_group_type_index, true).plural
        return `${groups[0].rollout_percentage ?? 100}% of ${population}`
    }
    return pluralize(groups.length, 'release condition')
}

function flagGlance(flag: FeatureFlagApi, aggregationLabel: TodayAggregationLabel): TodayObjectGlance {
    return {
        status: flag.active ? { label: 'Enabled', tone: 'success' } : { label: 'Disabled', tone: 'default' },
        description: flag.name && flag.name !== flag.key ? flag.name : undefined,
        facts: facts([
            ['Rollout', flagRollout(flag.filters, aggregationLabel)],
            ['Updated', since(flag.updated_at)],
        ]),
    }
}

function experimentGlance(experiment: ExperimentApi): TodayObjectGlance {
    return {
        status: experimentStatus(experiment),
        description: experiment.description || undefined,
        facts: facts([
            ['Flag', experiment.feature_flag_key],
            ['Started', experiment.start_date ? day(experiment.start_date) : null],
        ]),
    }
}

function surveyGlance(survey: SurveyApi): TodayObjectGlance {
    const questions = Array.isArray(survey.questions) ? survey.questions.length : 0
    return {
        status: lifecycle(survey.start_date, survey.end_date),
        description: survey.description || undefined,
        facts: facts([
            ['Questions', questions ? String(questions) : null],
            ['Started', survey.start_date ? day(survey.start_date) : null],
        ]),
    }
}

function cohortGlance(cohort: CohortApi): TodayObjectGlance {
    return {
        status: cohort.is_calculating
            ? { label: 'Calculating', tone: 'warning' }
            : cohort.errors_calculating
              ? { label: 'Calculation failed', tone: 'warning' }
              : undefined,
        headline:
            cohort.count !== null
                ? {
                      value: todayNumber(cohort.count),
                      caption: cohort.count === 1 ? 'person' : 'people',
                      series: [],
                      labels: [],
                  }
                : undefined,
        description: cohort.description || undefined,
        facts: facts([
            ['Kind', cohort.is_static ? 'Static' : 'Dynamic'],
            ['Calculated', since(cohort.last_calculation)],
        ]),
    }
}

function dashboardGlance(dashboard: DashboardApi): TodayObjectGlance {
    return {
        status: dashboard.pinned ? { label: 'Pinned', tone: 'default' } : undefined,
        description: dashboard.description || undefined,
        facts: facts([
            ['Tags', dashboard.tags?.map(String).join(', ')],
            ['Created by', dashboard.created_by?.first_name],
        ]),
    }
}

export async function fetchGlance(
    projectId: string,
    type: string | undefined,
    ref: string,
    format: TodayGlanceFormat
): Promise<TodayObjectGlance | null> {
    switch (baseObjectType(type)) {
        case 'insight': {
            const { results } = await insightsList(projectId, { short_id: ref, refresh: 'force_cache', limit: 1 })
            return results[0] ? insightGlance(results[0], format.currency) : null
        }
        case 'feature_flag':
            return flagGlance(await featureFlagsRetrieve(projectId, Number(ref)), format.aggregationLabel)
        case 'experiment':
            return experimentGlance(await experimentsRetrieve(projectId, Number(ref)))
        case 'survey':
            return surveyGlance(await surveysRetrieve(projectId, ref))
        case 'dashboard':
            return dashboardGlance(await dashboardsRetrieve(projectId, Number(ref)))
        case 'cohort':
            return cohortGlance(await cohortsRetrieve(projectId, Number(ref)))
        default:
            return null
    }
}
