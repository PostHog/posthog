import type { DeepPartialMap, ValidationErrorType } from 'kea-forms'

type StandardSchemaPathSegment =
    | PropertyKey
    | {
          key?: PropertyKey
      }

export interface StandardSchemaIssue {
    message: string
    path?: ReadonlyArray<StandardSchemaPathSegment>
}

export interface StandardSchemaSuccessResult<Output> {
    value: Output
    issues?: undefined
}

export interface StandardSchemaErrorResult {
    issues: ReadonlyArray<StandardSchemaIssue>
    value?: undefined
}

export type StandardSchemaResult<Output> = StandardSchemaSuccessResult<Output> | StandardSchemaErrorResult

export interface StandardSchemaV1<Input, Output> {
    '~standard': {
        validate: (value: Input) => StandardSchemaResult<Output> | Promise<StandardSchemaResult<Output>>
    }
}

export type ParseWithStandardSchemaResult<Input, Output> =
    | {
          success: true
          data: Output
      }
    | {
          success: false
          errors: DeepPartialMap<Input, ValidationErrorType>
      }

function getPathKey(segment: StandardSchemaPathSegment): PropertyKey | undefined {
    if (typeof segment === 'object' && segment !== null && 'key' in segment) {
        return segment.key
    }
    return segment
}

function appendIssueToErrors(
    errors: Record<PropertyKey, unknown>,
    path: ReadonlyArray<StandardSchemaPathSegment>,
    message: string
): void {
    let current: Record<PropertyKey, unknown> = errors

    if (path.length === 0) {
        const currentRootError = current._error
        if (Array.isArray(currentRootError)) {
            current._error = [...currentRootError, message]
        } else if (typeof currentRootError === 'string') {
            current._error = [currentRootError, message]
        } else {
            current._error = message
        }
        return
    }

    for (let index = 0; index < path.length; index++) {
        const key = getPathKey(path[index])

        if (key === undefined) {
            continue
        }

        const isLeaf = index === path.length - 1

        if (isLeaf) {
            const existingValue = current[key]
            if (Array.isArray(existingValue)) {
                current[key] = [...existingValue, message]
            } else if (typeof existingValue === 'string') {
                current[key] = [existingValue, message]
            } else {
                current[key] = message
            }
            return
        }

        const next = current[key]
        if (typeof next === 'object' && next !== null && !Array.isArray(next)) {
            current = next as Record<PropertyKey, unknown>
            continue
        }

        const newBranch: Record<PropertyKey, unknown> = {}
        current[key] = newBranch
        current = newBranch
    }
}

function issuesToKeaErrors<Input>(
    issues: ReadonlyArray<StandardSchemaIssue>
): DeepPartialMap<Input, ValidationErrorType> {
    const errors: Record<PropertyKey, unknown> = {}

    for (const issue of issues) {
        appendIssueToErrors(errors, issue.path ?? [], issue.message)
    }

    return errors as DeepPartialMap<Input, ValidationErrorType>
}

function validateSync<Input, Output>(
    schema: StandardSchemaV1<Input, Output>,
    values: Input
): StandardSchemaResult<Output> {
    const result = schema['~standard'].validate(values)

    if (result instanceof Promise) {
        throw new Error('Standard Schema adapter currently supports sync validation only')
    }

    return result
}

export function standardSchemaToKeaErrors<Input, Output>(
    schema: StandardSchemaV1<Input, Output>,
    values: Input
): DeepPartialMap<Input, ValidationErrorType> {
    const result = validateSync(schema, values)

    if (!('issues' in result) || !result.issues?.length) {
        return {} as DeepPartialMap<Input, ValidationErrorType>
    }

    return issuesToKeaErrors<Input>(result.issues)
}

export function parseWithStandardSchema<Input, Output>(
    schema: StandardSchemaV1<Input, Output>,
    values: Input
): ParseWithStandardSchemaResult<Input, Output> {
    const result = validateSync(schema, values)

    if ('issues' in result && result.issues?.length) {
        return {
            success: false,
            errors: issuesToKeaErrors<Input>(result.issues),
        }
    }

    return {
        success: true,
        data: result.value,
    }
}
