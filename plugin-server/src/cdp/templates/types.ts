import { PropertyOperator } from '../../types'
import {
    HogBytecode,
    HogFunctionFilters,
    HogFunctionInputSchemaType,
    HogFunctionMasking,
    HogFunctionTypeType,
} from '../types'

export type SubTemplateId = 'early-access-feature-enrollment' | 'survey-response' | 'activity-log'

export type HogFunctionSubTemplate = {
    id: SubTemplateId
    name: string
    description?: string
    filters?: HogFunctionFilters
    masking?: HogFunctionMasking
    input_schema_overrides?: Record<string, Partial<HogFunctionInputSchemaType>>
    type?: HogFunctionTypeType
}
export type HogFunctionMapping = {
    filters?: HogFunctionFilters
    inputs?: Record<string, any>
    inputs_schema?: Record<string, any>
}

export type HogFunctionMappingTemplate = HogFunctionMapping & {
    name: string
    include_by_default?: boolean
}

export type HogFunctionTemplate = {
    status: 'alpha' | 'beta' | 'stable' | 'free' | 'client-side'
    type: HogFunctionTypeType
    id: string
    name: string
    description: string
    hog: string
    inputs_schema: HogFunctionInputSchemaType[]
    category: string[]
    sub_templates?: HogFunctionSubTemplate[]
    filters?: HogFunctionFilters
    mappings?: HogFunctionMapping[]
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
}
