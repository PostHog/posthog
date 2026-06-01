export interface ParsedField {
    path: string[]
    value: string
}

export interface ParseResult {
    isValid: boolean
    fields: ParsedField[]
}

export type ConnectionStringParser = (str: string) => ParseResult
