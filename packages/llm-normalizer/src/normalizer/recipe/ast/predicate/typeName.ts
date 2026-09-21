export type TypeName = 'string' | 'array' | 'object' | 'null' | 'number' | 'boolean' | 'any'

export function matchesType(value: unknown, type: TypeName): boolean {
    switch (type) {
        case 'any':
            return true
        case 'string':
            return typeof value === 'string'
        case 'number':
            return typeof value === 'number'
        case 'boolean':
            return typeof value === 'boolean'
        case 'null':
            return value === null
        case 'array':
            return Array.isArray(value)
        case 'object':
            return value !== null && typeof value === 'object' && !Array.isArray(value)
    }
}
