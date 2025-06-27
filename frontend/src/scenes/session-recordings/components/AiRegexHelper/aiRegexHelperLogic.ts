import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import posthog from 'posthog-js'

import type { aiRegexHelperLogicType } from './aiRegexHelperLogicType'

export const aiRegexHelperLogic = kea<aiRegexHelperLogicType>([
    path(['lib', 'components', 'AiRegexHelper', 'aiRegexHelperLogic']),
    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setInput: (input: string) => ({ input }),
        handleGenerateRegex: true,
        handleCopyToClipboard: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setGeneratedRegex: (generatedRegex: string) => ({ generatedRegex }),
        setError: (error: string) => ({ error }),
        onClose: true,
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
            posthog.capture('ai_regex_helper_generate_regex')
            actions.setIsLoading(true)
            actions.setError('')
            actions.setGeneratedRegex('')

            try {
                const content = await api.recordings.aiRegex(values.input)

                if (content.hasOwnProperty('result') && content.result === 'success') {
                    posthog.capture('ai_regex_helper_generate_regex_success')
                    actions.setGeneratedRegex(content.data.output)
                } else if (content.hasOwnProperty('result') && content.result === 'error') {
                    posthog.capture('ai_regex_helper_generate_regex_error')
                    actions.setError(content.data.output)
                } else {
                    posthog.capture('ai_regex_helper_generate_regex_unknown_error')
                    actions.setError('Failed to generate regex. Try again?')
                }
            } catch {
                posthog.capture('ai_regex_helper_generate_regex_unknown_error')
                actions.setError('Failed to generate regex. Try again?')
            }

            actions.setIsLoading(false)
        },
        handleCopyToClipboard: async () => {
            try {
                await copyToClipboard(values.generatedRegex, 'Regex copied to clipboard')
            } catch {
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
