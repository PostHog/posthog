// Type aliases for usage in json-schema.

// Integer (any whole number)
/** @asType integer */
export type integer = number

// Non-negative integer (0, 1, 2, ...)
/**
 * @asType integer
 * @minimum 0
 */
export type non_negative_integer = number

// Positive integer (1, 2, 3, ...)
/**
 * @asType integer
 * @minimum 1
 */
export type positive_integer = number

// Negative integer (..., -2, -1)
/**
 * @asType integer
 * @maximum -1
 */
export type negative_integer = number

// Non-positive integer (..., -2, -1, 0)
/**
 * @asType integer
 * @maximum 0
 */
export type non_positive_integer = number

// Type alias for a numerical key. Needs to be reflected as string in json-schema, as JSON only supports string keys.
/** @asType string */
export type numerical_key = number
