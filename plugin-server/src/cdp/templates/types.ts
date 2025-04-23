import { PropertyOperator } from '../../types'
import {
    HogBytecode,
    HogFunctionFilters,
    HogFunctionInputSchemaType,
    HogFunctionMappingType,
    HogFunctionMasking,
    HogFunctionTypeType,
} from '../types'

export type SubTemplateId =
    | 'early-access-feature-enrollment'
    | 'survey-response'
    | 'activity-log'
    | 'error-tracking-issue-created'
    | 'error-tracking-issue-reopened'
    | 'insight-alert-firing'

export type HogFunctionSubTemplate = {
    id: SubTemplateId
    name: string
    free?: boolean
    description?: string
    filters?: HogFunctionFilters
    masking?: HogFunctionMasking
    input_schema_overrides?: Record<string, Partial<HogFunctionInputSchemaType>>
    type?: HogFunctionTypeType
}

export type HogFunctionMappingTemplate = HogFunctionMappingType & {
    name: string
    include_by_default?: boolean
}

export type HogFunctionTemplate = {
    status: 'stable' | 'alpha' | 'beta' | 'deprecated'
    free: boolean
    type: HogFunctionTypeType
    id: string
    name: string
    description: string
    hog: string
    inputs_schema: HogFunctionInputSchemaType[]
    category: string[]
    sub_templates?: HogFunctionSubTemplate[]
    filters?: HogFunctionFilters
    mappings?: HogFunctionMappingType[]
    mapping_templates?: HogFunctionMappingTemplate[]
    masking?: HogFunctionMasking
    icon_url?: string
}

export type HogFunctionTemplateCompiled = HogFunctionTemplate & {
    bytecode: HogBytecode
}

export const SUB_TEMPLATE_COMMON: Record<SubTemplateId, HogFunctionSubTemplate> = {
    'survey-response': {
        id: 'survey-response',
        name: 'Survey Response',
        filters: {
            events: [
                {
                    id: 'survey sent',
                    type: 'events',
                    properties: [
                        {
                            key: '$survey_response',
                            type: 'event',
                            value: 'is_set',
                            operator: PropertyOperator.IsSet,
                        },
                    ],
                },
            ],
        },
    },
    'early-access-feature-enrollment': {
        id: 'early-access-feature-enrollment',
        name: 'Early Access Feature Enrollment',
        filters: { events: [{ id: '$feature_enrollment_update', type: 'events' }] },
    },
    'activity-log': {
        id: 'activity-log',
        name: 'Team Activity',
        type: 'internal_destination',
        filters: { events: [{ id: '$activity_log_entry_created', type: 'events' }] },
    },
    'error-tracking-issue-created': {
        id: 'error-tracking-issue-created',
        name: 'Issue Created',
        type: 'internal_destination',
        free: true,
        filters: { events: [{ id: '$error_tracking_issue_created', type: 'events' }] },
    },
    'error-tracking-issue-reopened': {
        id: 'error-tracking-issue-reopened',
        name: 'Issue Reopened',
        type: 'internal_destination',
        free: true,
        filters: { events: [{ id: '$error_tracking_issue_reopened', type: 'events' }] },
    },
    'insight-alert-firing': {
        id: 'insight-alert-firing',
        name: 'Insight Alert Firing',
        filters: {
            events: [
                {
                    id: '$insight_alert_firing',
                    type: 'events',
                },
            ],
        },
    },
}
