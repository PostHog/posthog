import { tryJsonParse } from 'lib/utils/json'
import { LiquidRenderer } from 'lib/utils/liquid'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

export type CyclotronJobInputsValidationResult = {
    valid: boolean
    errors: Record<string, string>
    warnings: Record<string, string>
}

// Roots of the templating globals available to hog functions. Anchoring the
// mismatch heuristics on these keeps false positives down — literal braces in
// JSON/text bodies won't trip them unless they look like a global reference.
const GLOBAL_ROOTS = 'event|person|groups|inputs|source|project'

// A global root immediately followed by property access (`.field` or `[…]`). Requiring the
// access form is what distinguishes a real expression (`person.properties.email`) from a
// literal JSON key that happens to be named after a global (`{"event": "pageview"}`).
const GLOBAL_REFERENCE = `\\b(${GLOBAL_ROOTS})\\s*[.\\[]`

export const TEMPLATING_MISMATCH_WARNINGS = {
    // Hog single-brace expression authored in a Liquid field — rendered literally.
    hogSyntaxInLiquidField:
        'This looks like Hog syntax ({…}), but the field uses Liquid templating which expects {{ … }}. It will be sent as literal text — switch the templating engine to Hog, or use {{ … }}.',
    // Liquid double-brace expression authored in a Hog field.
    liquidSyntaxInHogField:
        'This looks like Liquid syntax ({{ … }}), but the field uses Hog templating which expects { … }. Switch the templating engine to Liquid, or use single braces.',
    // Bare global path with no braces at all — sent literally by either engine. The
    // suggested fix differs: Hog wraps in { … }, Liquid in {{ … }}.
    unbracedExpressionInHogField: (expression: string): string =>
        `This will be sent as literal text. Did you mean {${expression}}? Wrap it in braces to use the value.`,
    unbracedExpressionInLiquidField: (expression: string): string =>
        `This will be sent as literal text. Did you mean {{ ${expression} }}? Wrap it in braces to use the value.`,
} as const

/**
 * Detect when a value is authored in the wrong templating syntax for its engine.
 * These are non-blocking warnings: the value still saves, but it would be sent
 * literally rather than evaluated (e.g. `person.properties.email` with no braces,
 * or `{ … }` hog syntax in a Liquid field).
 */
const detectTemplatingMismatch = (value: unknown, language: 'hog' | 'liquid'): string | undefined => {
    if (typeof value !== 'string' || !value) {
        return
    }

    // A bare global path with no braces at all is literal in BOTH engines, so check it
    // regardless of language — only the suggested brace style differs.
    if (!value.includes('{') && new RegExp(`^(${GLOBAL_ROOTS})(\\.[\\w$]+|\\[[^\\]]+\\])+$`).test(value.trim())) {
        return language === 'liquid'
            ? TEMPLATING_MISMATCH_WARNINGS.unbracedExpressionInLiquidField(value.trim())
            : TEMPLATING_MISMATCH_WARNINGS.unbracedExpressionInHogField(value.trim())
    }

    if (language === 'liquid') {
        // Strip valid Liquid ({{ }} / {% %}) first, then look for leftover hog-style
        // single-brace expressions referencing a global — those render literally.
        const withoutLiquid = value.replace(/\{\{[\s\S]*?\}\}/g, '').replace(/\{%[\s\S]*?%\}/g, '')
        if (new RegExp(`\\{[^{}]*${GLOBAL_REFERENCE}[^{}]*\\}`).test(withoutLiquid)) {
            return TEMPLATING_MISMATCH_WARNINGS.hogSyntaxInLiquidField
        }
        return
    }

    // Hog field
    if (new RegExp(`\\{\\{[^}]*${GLOBAL_REFERENCE}[^}]*\\}\\}`).test(value)) {
        return TEMPLATING_MISMATCH_WARNINGS.liquidSyntaxInHogField
    }
}

const detectInputWarning = (
    input: CyclotronJobInputType,
    inputSchema: CyclotronJobInputSchemaType
): string | undefined => {
    if (!input || input.secret) {
        return
    }
    if (inputSchema.templating === false) {
        return
    }
    const language = input.templating ?? 'hog'

    if (['string', 'json'].includes(inputSchema.type)) {
        return detectTemplatingMismatch(input.value, language)
    }

    if (inputSchema.type === 'dictionary' && input.value && typeof input.value === 'object') {
        for (const val of Object.values(input.value)) {
            const warning = detectTemplatingMismatch(val, language)
            if (warning) {
                return warning
            }
        }
    }
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
        // When templating is enabled (default), boolean fields can be template strings
        if (inputSchema.templating === false || typeof value !== 'string') {
            return 'Value must be a boolean'
        }
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
        // `native_email` stores `to` as { name, email }; the legacy `email` type stores a bare address string.
        // Pull out the address so it gets the same required + templating validation as every other field —
        // otherwise a malformed Liquid template in the To field (or an empty address) saves with no error.
        const toEmail = value.to && typeof value.to === 'object' ? value.to.email : value.to
        const emailTemplateErrors: Partial<EmailTemplate> = {
            html:
                !value.html && !value.text
                    ? 'HTML or plain text is required'
                    : value.html
                      ? getTemplatingError(value.html)
                      : undefined,
            text: value.text ? getTemplatingError(value.text) : undefined,
            subject: !value.subject ? 'Subject is required' : getTemplatingError(value.subject),
            from: !value.from ? 'From is required' : getTemplatingError(value.from),
            to: !toEmail ? 'To is required' : getTemplatingError(toEmail),
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
        const inputWarnings: Record<string, string> = {}

        inputsSchema?.forEach((inputSchema) => {
            const input = inputs[inputSchema.key]
            const error = validateInput(input, inputSchema)
            if (error) {
                inputErrors[inputSchema.key] = error
            }
            const warning = detectInputWarning(input, inputSchema)
            if (warning) {
                inputWarnings[inputSchema.key] = warning
            }
        })

        return {
            // Warnings are intentionally excluded from `valid` — they never block save.
            valid: Object.keys(inputErrors).length === 0,
            errors: inputErrors,
            warnings: inputWarnings,
        }
    }
}
