import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { aiRegexHelperLogicType } from './aiRegexHelperLogicType'

export const aiRegexHelperLogic = kea<aiRegexHelperLogicType>([
    path(['lib', 'components', 'AiRegexHelper', 'aiRegexHelperLogic']),
    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setInput: (input: string) => ({ input }),
        handleGenerateRegex: () => ({}),
        handleApplyRegex: () => ({}),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setGeneratedRegex: (generatedRegex: string) => ({ generatedRegex }),
        setError: (error: string) => ({ error }),
        onClose: () => ({}),
    }),
    reducers({
        isOpen: [
            false,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
            },
        ],
        input: [
            '',
            {
                setInput: (_, { input }) => input,
            },
        ],
        isLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
            },
        ],
        generatedRegex: [
            '',
            {
                setGeneratedRegex: (_, { generatedRegex }) => generatedRegex,
            },
        ],
        error: [
            '',
            {
                setError: (_, { error }) => error,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        handleGenerateRegex: async () => {
            actions.setIsLoading(true)

            const content = await api.recordings.aiRegex(values.input)

            if (content.hasOwnProperty('result') && content.result === 'success') {
                actions.setGeneratedRegex(content.data.output)
            }
            if (content.hasOwnProperty('result') && content.result === 'error') {
                actions.setError(content.data.output)
            }

            actions.setIsLoading(false)
        },
        handleApplyRegex: async () => {
            try {
                await navigator.clipboard.writeText(values.generatedRegex)
                lemonToast.success('Regex copied to clipboard')
            } catch (error) {
                lemonToast.error('Failed to copy regex to clipboard')
            }
        },
        onClose: () => {
            actions.setIsOpen(false)
            actions.setInput('')
            actions.setGeneratedRegex('')
            actions.setError('')
        },
    })),
])
