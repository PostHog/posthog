import { kea } from 'kea'

import type { hogFunctionInputLogicType } from './HogFunctionInputLogicType'

export interface HogFunctionInputLogicProps {
    fieldKey: string
    initialValue?: string
    onChange?: (value: string) => void
}

export const hogFunctionInputLogic = kea<hogFunctionInputLogicType>({
    path: ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionInputLogic'],
    props: {} as HogFunctionInputLogicProps,
    key: (props: HogFunctionInputLogicProps) => `json_validation_${props.fieldKey}`,

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

    listeners: ({ actions, props }: { actions: any; props: HogFunctionInputLogicProps }) => {
        let timeout: number | null = null

        return {
            setJsonValue: ({ value }: { value: string }) => {
                // Don't validate empty values
                if (!value || value.trim() === '') {
                    actions.setError(null)
                    return
                }

                // Notify parent about the change
                props.onChange?.(value)

                // Clear any existing timeout to reset the timer
                if (timeout !== null) {
                    clearTimeout(timeout)
                }

                // Set a new timeout - only validate after user stops typing
                timeout = window.setTimeout(() => {
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
                    timeout = null
                }, 600)
            },
        }
    },

    // Initialize on props changes or mounting
    propsChanged: ({ actions, props }: { actions: any; props: HogFunctionInputLogicProps }) => {
        if (props.initialValue !== undefined) {
            actions.setJsonValue(props.initialValue)
        }
    },
})
