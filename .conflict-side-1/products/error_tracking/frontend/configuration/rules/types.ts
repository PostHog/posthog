import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { JsonType, UniversalFiltersGroup } from '~/types'

type ErrorTrackingBaseRule = {
    id: string
    filters: UniversalFiltersGroup
    order_key: number
}

export type ErrorTrackingSuppressionRule = ErrorTrackingBaseRule

export type ErrorTrackingAssignmentRule = ErrorTrackingBaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
    disabled_data: JsonType | null
}

export type ErrorTrackingGroupingRule = ErrorTrackingBaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
    disabled_data: JsonType | null
    description?: string
}

export type ErrorTrackingRule = ErrorTrackingSuppressionRule | ErrorTrackingGroupingRule | ErrorTrackingAssignmentRule
export type ErrorTrackingRuleNew = ErrorTrackingRule & { id: 'new' }

export enum ErrorTrackingRuleType {
    Assignment = 'assignment_rules',
    Grouping = 'grouping_rules',
    Suppression = 'suppression_rules',
}

export type ErrorTrackingRulesLogicProps = {
    ruleType: ErrorTrackingRuleType
}
