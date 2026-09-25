import type { Node } from '~/queries/schema/schema-general'

/** Mirrors TypesafeSubjectSerializer in products/product_analytics/backend/presentation/typesafe_suggestions.py. */
export interface TypesafeSubjectPayload {
    subject: 'insight' | 'dashboard'
    query?: Node | null
    name?: string
    description?: string
    tile_names?: string[]
}

export interface TypesafeDashboardCandidate {
    id: number
    name: string
    description?: string
}

export interface TypesafeTextSuggestion {
    value: string
    confidence: number
    candidates: string[]
    /** The second most likely candidate, so the UI can say what else was considered when the pick is unchanged. */
    runner_up: string | null
}

export interface TypesafeTagSuggestion {
    tags: string[]
    scores: Record<string, number>
}

export interface TypesafeDashboardSuggestion {
    dashboard_id: number | null
    confidence: number
}
