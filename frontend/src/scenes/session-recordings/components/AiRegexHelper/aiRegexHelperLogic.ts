import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { aiRegexHelperLogicType } from './aiRegexHelperLogicType'

const GENERIC_ERROR = 'Failed to generate regex. Try again?'

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

                if (content?.result === 'success' && content.data?.output) {
                    posthog.capture('ai_regex_helper_generate_regex_success')
                    actions.setGeneratedRegex(content.data.output)
                } else if (content?.result === 'error') {
                    posthog.capture('ai_regex_helper_generate_regex_error')
                    actions.setError(content.data?.output || GENERIC_ERROR)
                } else {
                    posthog.capture('ai_regex_helper_generate_regex_unknown_error')
                    actions.setError(GENERIC_ERROR)
                }
            } catch (error) {
                // Surface the server-provided detail (e.g. a DRF ValidationError message) so the user
                // sees something actionable instead of the same opaque retry banner for every failure.
                const detail = error instanceof ApiError ? error.detail : null
                posthog.capture('ai_regex_helper_generate_regex_unknown_error', {
                    error_status: error instanceof ApiError ? error.status : undefined,
                    error_detail: detail,
                })
                actions.setError(detail || GENERIC_ERROR)
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
