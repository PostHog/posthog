import {
    HogBytecode,
    HogFunctionFilters,
    HogFunctionInputSchemaType,
    HogFunctionMappingType,
    HogFunctionMasking,
    HogFunctionTypeType,
} from '../types'

export type HogFunctionMappingTemplate = HogFunctionMappingType & {
    name: string
    include_by_default?: boolean
}

export type HogFunctionTemplate = {
    status: 'stable' | 'alpha' | 'beta' | 'deprecated' | 'requestable'
    free: boolean
    type: HogFunctionTypeType
    id: string
    name: string
    description: string
    hog: string
    inputs_schema: HogFunctionInputSchemaType[]
    category: string[]
    filters?: HogFunctionFilters
    mappings?: HogFunctionMappingType[]
    mapping_templates?: HogFunctionMappingTemplate[]
    masking?: HogFunctionMasking
    icon_url?: string
}

export type HogFunctionTemplateCompiled = HogFunctionTemplate & {
    bytecode: HogBytecode
}
