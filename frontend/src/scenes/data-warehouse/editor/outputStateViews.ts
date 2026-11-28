import type { ComponentType } from 'react'

import type { HogQLQuery, DataVisualizationNode } from '~/queries/schema/schema-general'

export interface OutputErrorViewProps {
    /** The message as the database or HogQL reported it. */
    error: string | null | undefined
    /** A HogQL validation message, which reads better than the raw error when there is one. */
    validationError: string | false | null | undefined
    validationErrorCode: string | null | undefined
    cancelled: boolean
    sourceQuery: DataVisualizationNode | HogQLQuery
    showQueryScan: boolean
}

/**
 * The results pane's non-data states. The Lemon pane and the quill workspace each supply a set, so
 * the pane picks one set per surface instead of branching on the surface in every state.
 */
export interface OutputStateViews {
    Empty: ComponentType<{ kind: 'results' | 'chart' }>
    NoRows: ComponentType
    Error: ComponentType<OutputErrorViewProps>
    ChoosingChart: ComponentType<{ onSkip: () => void }>
}
