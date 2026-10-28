import { CHECKS_LIMIT } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import type { OverviewStats } from './modelsOverviewLogic'

export type StatTone = 'danger' | 'warning' | null

export interface OverviewStatItem {
    label: string
    value: string
    loading: boolean
    tone: StatTone
    tooltip?: string
    dataAttr: string
}

export interface OverviewStatInputs {
    stats: OverviewStats
    brokenModelCount: number
    modelsFirstLoading: boolean
    checksFirstLoading: boolean
}

function checksTooltip({ failingChecks, failingChecksIsLowerBound }: OverviewStats): string | undefined {
    if (failingChecks === null) {
        return 'Checks could not be loaded'
    }
    return failingChecksIsLowerBound ? `Only the first ${CHECKS_LIMIT} checks were read` : undefined
}

function modelStatItems({ stats, brokenModelCount, modelsFirstLoading }: OverviewStatInputs): OverviewStatItem[] {
    if (!modelsFirstLoading && stats.models === null) {
        return []
    }
    const materializationIssues = stats.materializationIssues ?? 0
    return [
        {
            label: 'Models',
            value: String(stats.models ?? 0),
            loading: modelsFirstLoading,
            tone: null,
            dataAttr: 'models-overview-stat-models',
        },
        {
            label: 'Materialized',
            value: String(stats.materialized ?? 0),
            loading: modelsFirstLoading,
            tone: null,
            dataAttr: 'models-overview-stat-materialized',
        },
        {
            label: 'Materialization issues',
            value: String(materializationIssues),
            loading: modelsFirstLoading,
            tone: materializationIssues === 0 ? null : brokenModelCount > 0 ? 'danger' : 'warning',
            dataAttr: 'models-overview-stat-attention',
        },
    ]
}

export function overviewStatItems(inputs: OverviewStatInputs): OverviewStatItem[] {
    const { failingChecks, failingChecksIsLowerBound } = inputs.stats
    return [
        ...modelStatItems(inputs),
        {
            label: 'Failing checks',
            value: failingChecks === null ? '-' : `${failingChecks}${failingChecksIsLowerBound ? '+' : ''}`,
            loading: inputs.checksFirstLoading,
            tone: failingChecks ? 'danger' : null,
            tooltip: checksTooltip(inputs.stats),
            dataAttr: 'models-overview-stat-checks',
        },
    ]
}
