// Type alias for number to be reflected as integer in json-schema.
/** @asType integer */
export type integer = number

// Type alias for a numerical key. Needs to be reflected as string in json-schema, as JSON only supports string keys.
/** @asType string */
export type numerical_key = number
