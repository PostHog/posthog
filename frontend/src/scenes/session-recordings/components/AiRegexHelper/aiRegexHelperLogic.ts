import { actions, connect, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import posthog from 'posthog-js'
import { replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'

import { SessionReplayUrlTriggerConfig } from '~/types'

import type { aiRegexHelperLogicType } from './aiRegexHelperLogicType'

export const aiRegexHelperLogic = kea<aiRegexHelperLogicType>([
    connect(replayTriggersLogic),
    path(['lib', 'components', 'AiRegexHelper', 'aiRegexHelperLogic']),
    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setInput: (input: string) => ({ input }),
        handleGenerateRegex: true,
        handleApplyRegex: (type: 'trigger' | 'blocklist') => ({ type }),
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

            const content = await api.recordings.aiRegex(values.input)

            if (content.hasOwnProperty('result') && content.result === 'success') {
                posthog.capture('ai_regex_helper_generate_regex_success')
                actions.setGeneratedRegex(content.data.output)
            }
            if (content.hasOwnProperty('result') && content.result === 'error') {
                posthog.capture('ai_regex_helper_generate_regex_error')
                actions.setError(content.data.output)
            }

            actions.setIsLoading(false)
        },
        handleCopyToClipboard: async () => {
            try {
                await copyToClipboard(values.generatedRegex, 'Regex copied to clipboard')
            } catch (error) {
                lemonToast.error('Failed to copy regex to clipboard')
            }
        },
        handleApplyRegex: async ({ type }) => {
            try {
                const payload: SessionReplayUrlTriggerConfig = { url: values.generatedRegex, matching: 'regex' }
                if (type === 'trigger') {
                    await replayTriggersLogic.asyncActions.addUrlTrigger(payload)
                } else {
                    await replayTriggersLogic.asyncActions.addUrlBlocklist(payload)
                }
            } catch (error) {
                lemonToast.error('Failed to apply regex')
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
