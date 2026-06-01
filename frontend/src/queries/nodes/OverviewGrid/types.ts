import { WebAnalyticsItemKind } from '~/queries/schema/schema-general'

// Kept in a types-only module (depends solely on schema-general) so that foundational modules like
// ~/queries/types can reference OverviewItem without pulling in the OverviewGrid component graph,
// which would create an import cycle.
export interface OverviewItem {
    key: string
    value: number | string | undefined
    previous?: number | string | undefined
    changeFromPreviousPct?: number | undefined
    kind: WebAnalyticsItemKind
    isIncreaseBad?: boolean
    warning?: string
    warningLink?: string
}
