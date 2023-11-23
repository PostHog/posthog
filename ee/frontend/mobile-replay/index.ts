import { eventWithTime } from '@rrweb/types'
import Ajv, { ErrorObject } from 'ajv'

import mobileSchema from './schema/mobile/rr-mobile-schema.json'
import webSchema from './schema/web/rr-web-schema.json'
import { makeFullEvent, makeMetaEvent } from './transformers'

const ajv = new Ajv() // options can be passed, e.g. {allErrors: true}

const transformers: Record<number, (x: any) => eventWithTime> = {
    4: makeMetaEvent,
    10: makeFullEvent,
}

const mobileSchemaValidator = ajv.compile(mobileSchema)

export function validateFromMobile(data: unknown): {
    isValid: boolean
    errors: ErrorObject[] | null | undefined
} {
    const isValid = mobileSchemaValidator(data)
    return {
        isValid,
        errors: isValid ? null : mobileSchemaValidator.errors,
    }
}

const webSchemaValidator = ajv.compile(webSchema)

export class TransformationError implements Error {
    name = 'TransformationError'
    message = 'Failed to transform to web schema'
    errors: ErrorObject<string, Record<string, unknown>, unknown>[] | null | undefined

    constructor(_errors: ErrorObject<string, Record<string, unknown>, unknown>[] | null | undefined) {
        this.errors = _errors
    }
}

export function transformToWeb(mobileData: any[]): string {
    const response = mobileData.reduce((acc, event) => {
        const transformer = transformers[event.type]
        if (!transformer) {
            console.warn(`No transformer for event type ${event.type}`)
        } else {
            const transformed = transformer(event)
            validateAgainstWebSchema(transformed)
            acc.push(transformed)
        }
        return acc
    }, [])

    return JSON.stringify(response)
}

export function validateAgainstWebSchema(data: unknown): boolean {
    const validationResult = webSchemaValidator(data)
    if (!validationResult) {
        console.error(webSchemaValidator.errors)
        throw new TransformationError(webSchemaValidator.errors)
    }
    return validationResult
}
