import { CustomError } from 'ts-custom-error'

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
    status: 'stable' | 'alpha' | 'beta' | 'deprecated' | 'coming_soon' | 'hidden'
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

export class IntegrationError extends CustomError {
    code: string | undefined
    status: number | undefined
    retry?: boolean

    /**
     * @param message - a human-friendly message to display to users
     * @param code - error code/reason
     * @param status - http status code (e.g. 400)
     *    - 4xx errors are not automatically retried, except for 408, 423, 429
     *    - 5xx are automatically retried, except for 501
     */
    constructor(message: string, code: string, status: number) {
        super(message)
        this.status = status
        this.code = code
    }
}

export type Response = {
    status: number
    data: any
    content: string
    headers: Record<string, any>
}

export type NativeTemplate = Omit<HogFunctionTemplate, 'hog'> & {
    perform: (
        request: (
            url: string,
            options: {
                method?: 'POST' | 'GET' | 'PATCH' | 'PUT' | 'DELETE'
                headers: Record<string, any>
                json?: any
                body?: string | URLSearchParams
                throwHttpErrors?: boolean
                searchParams?: Record<string, any>
            }
        ) => Promise<Response>,
        inputs: Record<string, any>
    ) => Promise<void>
}
