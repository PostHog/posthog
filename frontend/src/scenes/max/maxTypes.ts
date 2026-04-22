import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { DashboardFilter, HogQLVariable, QuerySchema } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

// eslint-disable-next-line import/no-cycle
import { RevenueAnalyticsQuery } from 'products/revenue_analytics/frontend/revenueAnalyticsLogic'

export enum MaxContextType {
    DASHBOARD = 'dashboard',
    INSIGHT = 'insight',
    EVENT = 'event',
    ACTION = 'action',
    ERROR_TRACKING_ISSUE = 'error_tracking_issue',
    EVALUATION = 'evaluation',
    NOTEBOOK = 'notebook',
}

export type InsightWithQuery = Pick<
    Partial<QueryBasedInsightModel>,
    'query' | 'short_id' | 'name' | 'derived_name' | 'description' | 'id'
>

export interface MaxInsightContext {
    type: MaxContextType.INSIGHT
    id: InsightShortId
    name?: string | null
    description?: string | null
    query: QuerySchema // The actual query node, e.g., TrendsQuery, HogQLQuery
    filtersOverride?: DashboardFilter
    variablesOverride?: Record<string, HogQLVariable>
}

export interface MaxDashboardContext {
    type: MaxContextType.DASHBOARD
    id: integer
    name?: string | null
    description?: string | null
    insights: MaxInsightContext[]
    filters: DashboardFilter
}

export interface MaxEventContext {
    type: MaxContextType.EVENT
    id: string
    name?: string | null
    description?: string | null
}

export interface MaxActionContext {
    type: MaxContextType.ACTION
    id: integer
    name: string
    description?: string | null
}

export interface MaxErrorTrackingIssueContext {
    type: MaxContextType.ERROR_TRACKING_ISSUE
    id: string // UUID of the error tracking issue
    name?: string | null
}

export interface MaxEvaluationContext {
    type: MaxContextType.EVALUATION
    id: string
    name?: string | null
    description?: string | null
    evaluation_type: 'hog' | 'llm_judge'
    hog_source?: string | null
}

export interface MaxNotebookContext {
    type: MaxContextType.NOTEBOOK
    id: string // short_id
    name?: string | null
}

// The main shape for the UI context sent to the backend
export interface MaxUIContext {
    dashboards?: MaxDashboardContext[]
    insights?: MaxInsightContext[]
    events?: MaxEventContext[]
    actions?: MaxActionContext[]
    error_tracking_issues?: MaxErrorTrackingIssueContext[]
    evaluations?: MaxEvaluationContext[]
    notebooks?: MaxNotebookContext[]
    form_answers?: Record<string, string> // question_id -> answer for create_form tool responses
}

// Taxonomic filter options
export interface MaxContextTaxonomicFilterOption {
    id: string
    value: string | integer
    name: string
    icon: React.ComponentType
    type?: MaxContextType
}

// Union type for all possible context payloads that can be exposed by scene logics
export type MaxContextItem =
    | MaxInsightContext
    | MaxDashboardContext
    | MaxEventContext
    | MaxActionContext
    | MaxErrorTrackingIssueContext
    | MaxEvaluationContext
    | MaxNotebookContext

type MaxInsightContextInput = {
    type: MaxContextType.INSIGHT
    data: InsightWithQuery
    filtersOverride?: DashboardFilter
    variablesOverride?: Record<string, HogQLVariable>
    revenueAnalyticsQuery?: RevenueAnalyticsQuery
}
type MaxDashboardContextInput = {
    type: MaxContextType.DASHBOARD
    data: DashboardType<InsightWithQuery>
}
type MaxEventContextInput = {
    type: MaxContextType.EVENT
    data: EventDefinition
}
type MaxActionContextInput = {
    type: MaxContextType.ACTION
    data: ActionType
}
type MaxErrorTrackingIssueContextInput = {
    type: MaxContextType.ERROR_TRACKING_ISSUE
    data: { id: string; name?: string | null }
}
type MaxEvaluationContextInput = {
    type: MaxContextType.EVALUATION
    data: {
        id: string
        name?: string | null
        description?: string | null
        evaluation_type: 'hog' | 'llm_judge'
        hog_source?: string | null
    }
}
type MaxNotebookContextInput = {
    type: MaxContextType.NOTEBOOK
    data: { short_id: string; title?: string | null }
}
export type MaxContextInput =
    | MaxInsightContextInput
    | MaxDashboardContextInput
    | MaxEventContextInput
    | MaxActionContextInput
    | MaxErrorTrackingIssueContextInput
    | MaxEvaluationContextInput
    | MaxNotebookContextInput

function pickInsightFields(insight: Partial<QueryBasedInsightModel>): InsightWithQuery {
    return {
        id: insight.id,
        short_id: insight.short_id,
        name: insight.name,
        derived_name: insight.derived_name,
        description: insight.description,
        query: insight.query,
    }
}

/**
 * Helper functions to create maxContext items safely
 * These ensure proper typing and consistent patterns across scene logics
 */
export const createMaxContextHelpers = {
    dashboard: (dashboard: DashboardType<QueryBasedInsightModel>): MaxDashboardContextInput => ({
        type: MaxContextType.DASHBOARD,
        data: {
            ...dashboard,
            tiles: dashboard.tiles.map((tile) => ({
                ...tile,
                insight: tile.insight ? pickInsightFields(tile.insight) : tile.insight,
            })),
        },
    }),

    insight: (
        insight: InsightWithQuery,
        {
            filtersOverride,
            variablesOverride,
            revenueAnalyticsQuery,
        }: {
            filtersOverride?: DashboardFilter
            variablesOverride?: Record<string, HogQLVariable>
            revenueAnalyticsQuery?: RevenueAnalyticsQuery
        } = {}
    ): MaxInsightContextInput => ({
        type: MaxContextType.INSIGHT,
        data: pickInsightFields(insight),
        filtersOverride,
        variablesOverride,
        revenueAnalyticsQuery,
    }),

    event: (event: EventDefinition): MaxEventContextInput => ({
        type: MaxContextType.EVENT,
        data: event,
    }),

    action: (action: ActionType): MaxActionContextInput => ({
        type: MaxContextType.ACTION,
        data: action,
    }),

    errorTrackingIssue: (issue: { id: string; name?: string | null }): MaxErrorTrackingIssueContextInput => ({
        type: MaxContextType.ERROR_TRACKING_ISSUE,
        data: issue,
    }),

    evaluation: (evaluation: {
        id: string
        name?: string | null
        description?: string | null
        evaluation_type: 'hog' | 'llm_judge'
        hog_source?: string | null
    }): MaxEvaluationContextInput => ({
        type: MaxContextType.EVALUATION,
        data: evaluation,
    }),

    notebook: (notebook: { short_id: string; title?: string | null }): MaxNotebookContextInput => ({
        type: MaxContextType.NOTEBOOK,
        data: notebook,
    }),
}

export function isAgentMode(mode: unknown): mode is AgentMode {
    return typeof mode === 'string' && Object.values(AgentMode).includes(mode as AgentMode)
}
