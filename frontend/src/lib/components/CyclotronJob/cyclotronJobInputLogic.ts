import { kea } from 'kea'

import type { cyclotronJobInputLogicType } from './cyclotronJobInputLogicType'

export interface CyclotronJobInputLogicProps {
    fieldKey: string
    initialValue?: string
    onChange?: (value: string) => void
}

/**
 * Format a JSON value for display in the editor
 */
export function formatJsonValue(value: any): string {
    if (value === undefined || value === null) {
        return '{}'
    }

    return typeof value !== 'string' ? JSON.stringify(value, null, 2) : value
}

export const cyclotronJobInputLogic = kea<cyclotronJobInputLogicType>({
    path: ['lib', 'components', 'CyclotronJob', 'cyclotronJobInputLogic'],
    props: {} as CyclotronJobInputLogicProps,
    key: (props: CyclotronJobInputLogicProps) => `json_validation_${props.fieldKey}`,

    actions: {
        setJsonValue: (value: string) => ({ value }),
        validateJson: (value: string) => ({ value }),
        setError: (error: string | null) => ({ error }),
    },

    reducers: {
        jsonValue: [
            '' as string,
            {
                setJsonValue: (_state: string, { value }: { value: string }) => value,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_state: string | null, { error }: { error: string | null }) => error,
            },
        ],
    },

    selectors: {
        hasError: [(s: any) => [s.error], (error: string | null) => !!error],
    },

    listeners: ({ actions, props }) => ({
        setJsonValue: async ({ value }, breakpoint) => {
            // Don't validate empty values
            if (!value || value.trim() === '') {
                actions.setError(null)
                return
            }

            // Notify parent about the change
            props.onChange?.(value)

            // Wait for 600ms before validating, and break if setJsonValue is called again
            await breakpoint(600)

            try {
                JSON.parse(value)
                actions.setError(null)
            } catch (e: any) {
                // Prettify common errors
                let errorMessage = e.message || 'Invalid JSON'

                // Special case for undefined
                if (errorMessage.includes("'u'") && value.includes('undefined')) {
                    errorMessage = "Error: 'undefined' is not allowed in JSON. Use null instead."
                }

                actions.setError(errorMessage)
            }
        },
    }),

    // Initialize on props changes or mounting
    propsChanged({ actions, props }: { actions: any; props: CyclotronJobInputLogicProps }) {
        if (props.initialValue !== undefined) {
            actions.setJsonValue(formatJsonValue(props.initialValue))
        }
    },
})
