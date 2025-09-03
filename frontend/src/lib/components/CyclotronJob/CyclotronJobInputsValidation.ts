import { LiquidRenderer } from 'lib/utils/liquid'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

export type CyclotronJobInputsValidationResult = {
    valid: boolean
    errors: Record<string, string>
}

export class CyclotronJobInputsValidation {
    // Returns a list an object of errors for each input

    static validate(
        // oxlint-disable-next-line no-unused-vars
        inputs: Record<string, CyclotronJobInputType>,
        // oxlint-disable-next-line no-unused-vars
        inputsSchema: CyclotronJobInputSchemaType[]
    ): CyclotronJobInputsValidationResult {
        const inputErrors: Record<string, string> = {}

        inputsSchema?.forEach((inputSchema) => {
            const key = inputSchema.key
            const input = inputs[key]
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

            const addTemplatingError = (value: string): void => {
                const templatingError = getTemplatingError(value)
                if (templatingError) {
                    inputErrors[key] = templatingError
                }
            }

            const missing = value === undefined || value === null || value === ''
            if (inputSchema.required && missing) {
                inputErrors[key] = 'This field is required'
            }

            if (inputSchema.type === 'json' && typeof value === 'string') {
                try {
                    JSON.parse(value)
                } catch {
                    inputErrors[key] = 'Invalid JSON'
                }

                addTemplatingError(value)
            }

            if (inputSchema.type === 'email' && value) {
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
                    inputErrors[key] = combinedErrors
                }
            }

            if (inputSchema.type === 'string' && typeof value === 'string') {
                addTemplatingError(value)
            }

            if (inputSchema.type === 'dictionary') {
                for (const val of Object.values(value ?? {})) {
                    if (typeof val === 'string') {
                        addTemplatingError(val)
                    }
                }
            }
        })

        return {
            valid: Object.keys(inputErrors).length === 0,
            errors: inputErrors,
        }
    }
}
