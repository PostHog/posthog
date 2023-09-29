import { InsightLogicProps } from '~/types'

/** Pass custom metadata to queries. Used for e.g. custom columns in the DataTable. */
export interface QueryContext {
    /** Column templates for the DataTable */
    columns?: Record<string, QueryContextColumn>
    /** used to override the value in the query */
    showOpenEditorButton?: boolean
    showQueryEditor?: boolean
    /* Adds help and examples to the query editor component */
    showQueryHelp?: boolean
    insightProps?: InsightLogicProps
    emptyStateHeading?: string
    emptyStateDetail?: string
}

interface QueryContextColumn {
    title?: string
    render?: (props: { record: any }) => JSX.Element
}
