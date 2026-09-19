import { InputField } from '@segment/actions-core'

/**
 * Segment validates a mapped payload against the action's field schema before it calls `perform`,
 * and that step coerces each value into the type the field declares. `getFieldType` renders a field
 * declared as a number or an integer as a string input, so hog templating works on it, and a
 * templated boolean arrives as the word `concat` printed. This is the pass that turns the rendered
 * string back into what the destination declared. Without it a destination that branches on the
 * runtime type drops the value, and a field declared as an array throws when it is handed a
 * scalar.
 */

export type SegmentInputField = Partial<Pick<InputField, 'type' | 'multiple'>> & {
    properties?: Record<string, SegmentInputField | undefined>
}

const coerceScalar = (value: unknown, type: string | undefined): unknown => {
    if (typeof value !== 'string' || value === '') {
        return value
    }

    if (type === 'boolean') {
        // Hog prints a boolean as the exact lowercase word. Any other string is a value we cannot
        // read as a boolean without guessing, so it reaches the destination as the customer wrote it.
        if (value === 'true') {
            return true
        }
        if (value === 'false') {
            return false
        }
        return value
    }

    if (type !== 'number' && type !== 'integer') {
        return value
    }

    const parsed = Number(value)
    if (!Number.isFinite(parsed) || (type === 'integer' && !Number.isInteger(parsed))) {
        return value
    }
    return parsed
}

const coerceSingleValue = (value: unknown, field: SegmentInputField): unknown => {
    if (field.type === 'object') {
        if (typeof value !== 'object' || value === null || Array.isArray(value)) {
            return value
        }
        return coerceFields(value as Record<string, unknown>, field.properties)
    }

    return coerceScalar(value, field.type)
}

const coerceField = (value: unknown, field: SegmentInputField): unknown => {
    // An optional input that renders to nothing arrives as an empty string, and `multiple` would
    // wrap it into a one-element array. A destination that gates on an empty check then reads the
    // field as set, so an empty value is left as it is.
    if (value === null || value === undefined || value === '') {
        return value
    }

    if (field.multiple) {
        const items = Array.isArray(value) ? value : [value]
        return items.map((item) => coerceSingleValue(item, field))
    }

    return coerceSingleValue(value, field)
}

/**
 * Returns a copy of `values` with every key the schema declares coerced to its declared type. Keys
 * the schema does not declare pass through untouched, because the same object also carries the
 * destination settings and anything a customer added to a dictionary input.
 */
export const coerceFields = (
    values: Record<string, unknown>,
    fields: Record<string, SegmentInputField | undefined> | undefined
): Record<string, unknown> => {
    if (!fields) {
        return values
    }

    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values)) {
        const field = fields[key]
        result[key] = field ? coerceField(value, field) : value
    }
    return result
}
