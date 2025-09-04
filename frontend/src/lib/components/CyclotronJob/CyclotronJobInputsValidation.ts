import { tryJsonParse } from 'lib/utils'
import { LiquidRenderer } from 'lib/utils/liquid'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

export type CyclotronJobInputsValidationResult = {
    valid: boolean
    errors: Record<string, string>
}

const validateInput = (input: CyclotronJobInputType, inputSchema: CyclotronJobInputSchemaType): string | undefined => {
    const language = input?.templating ?? 'hog'
    const value = input?.value
    if (input?.secret) {
        // We leave unmodified secret values alone
        return
    }

    const getTemplatingError = (value: string): string | undefined => {
        if (language === 'liquid' && typeof value === 'string') {
            try {
                LiquidRenderer.parse(value)
            } catch (e: any) {
                return `Liquid template error: ${e.message}`
            }
        }
    }

    const missing = value === undefined || value === null || value === ''
    if (missing) {
        if (inputSchema.required) {
            return 'This field is required'
        }
        return undefined
    }

    if (inputSchema.type === 'string' && typeof value !== 'string') {
        return 'Value must be a string'
    } else if (inputSchema.type === 'number' && typeof value !== 'number') {
        return 'Value must be a number'
    } else if (inputSchema.type === 'boolean' && typeof value !== 'boolean') {
        return 'Value must be a boolean'
    } else if (inputSchema.type === 'dictionary' && typeof value !== 'object') {
        return 'Value must be a dictionary'
    } else if (inputSchema.type === 'integration' && typeof value !== 'number') {
        return 'Value must be an Integration ID'
    } else if (inputSchema.type === 'json') {
        if (!['string', 'object'].includes(typeof value)) {
            return 'Value must be valid json'
        }
        if (typeof value === 'string' && !tryJsonParse(value)) {
            return 'Invalid JSON'
        }
    }

    if (['email', 'native_email'].includes(inputSchema.type) && value) {
        const emailTemplateErrors: Partial<EmailTemplate> = {
            html: !value.html ? 'HTML is required' : getTemplatingError(value.html),
            subject: !value.subject ? 'Subject is required' : getTemplatingError(value.subject),
            // text: !value.text ? 'Text is required' : getTemplatingError(value.text),
            from: !value.from ? 'From is required' : getTemplatingError(value.from),
            to: !value.to ? 'To is required' : getTemplatingError(value.to),
        }

        const combinedErrors = Object.values(emailTemplateErrors)
            .filter((v) => !!v)
            .join(', ')

        if (combinedErrors) {
            return combinedErrors
        }
    }

    if (['string', 'json'].includes(inputSchema.type)) {
        const templatingError = getTemplatingError(value)
        if (templatingError) {
            return templatingError
        }
    }

    if (inputSchema.type === 'dictionary') {
        for (const val of Object.values(value ?? {})) {
            if (typeof val === 'string') {
                const templatingError = getTemplatingError(val)
                if (templatingError) {
                    return templatingError
                }
            }
        }
    }
}
export class CyclotronJobInputsValidation {
    static validate(
        inputs: Record<string, CyclotronJobInputType>,
        inputsSchema: CyclotronJobInputSchemaType[]
    ): CyclotronJobInputsValidationResult {
        const inputErrors: Record<string, string> = {}

        inputsSchema?.forEach((inputSchema) => {
            const input = inputs[inputSchema.key]
            const error = validateInput(input, inputSchema)
            if (error) {
                inputErrors[inputSchema.key] = error
            }
        })

        return {
            valid: Object.keys(inputErrors).length === 0,
            errors: inputErrors,
        }
    }
}
