/**
 * @fileoverview A component that helps you to generate regex for your settings using Max AI
 */
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconAI, IconCopy, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiRegexHelperLogic } from './aiRegexHelperLogic'

type AiRegexHelperProps = {
    onApply: (regex: string) => void
}

export function AiRegexHelper({ onApply }: AiRegexHelperProps): JSX.Element {
    const { isOpen, input, generatedRegex, error, isLoading } = useValues(aiRegexHelperLogic)
    const { setInput, handleGenerateRegex, onClose, handleCopyToClipboard } = useActions(aiRegexHelperLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    const { preflight } = useValues(preflightLogic)
    const aiAvailable = preflight?.openai_available

    const disabledReason = !aiAvailable
        ? 'To use AI features, set environment variable OPENAI_API_KEY for this instance of PostHog'
        : !dataProcessingAccepted
          ? dataProcessingApprovalDisabledReason || 'You must accept the data processing agreement to use AI features'
          : isLoading
            ? 'Generating...'
            : !input.length
              ? 'Provide a prompt first'
              : null

    return (
        <>
            <LemonModal isOpen={isOpen} onClose={onClose} title="Max AI Regex Helper">
                Explain your regex in natural language:
                <LemonTextArea
                    placeholder="I want a regex that covers all urls that include 'app.posthog.com/auth/*'"
                    className="w-full my-2"
                    maxRows={4}
                    minRows={2}
                    value={input}
                    onChange={(value) => setInput(value)}
                />
                <div className="flex flex-col gap-2 mt-2">
                    {generatedRegex && (
                        <div>
                            <h3 className="text-sm font-bold">Your regex is:</h3>
                            <div className="flex flex-row gap-2 justify-between items-center">
                                <LemonBanner type="info" className="w-full">
                                    {generatedRegex}
                                </LemonBanner>
                                <div>
                                    <LemonButton
                                        type="secondary"
                                        onClick={handleCopyToClipboard}
                                        tooltip="Copy to clipboard"
                                        icon={<IconCopy />}
                                    />
                                </div>
                            </div>
                        </div>
                    )}

                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={onClose} tooltip="Close">
                            Close
                        </LemonButton>

                        <AIConsentPopoverWrapper>
                            <LemonButton
                                type={generatedRegex ? 'secondary' : 'primary'}
                                onClick={handleGenerateRegex}
                                disabledReason={disabledReason}
                                loading={isLoading}
                            >
                                {generatedRegex ? 'Regenerate' : 'Generate Regex'}
                            </LemonButton>
                        </AIConsentPopoverWrapper>

                        {generatedRegex && (
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    posthog.capture('path_cleaning_regex_ai_applied', {
                                        prompt: input,
                                        regex: generatedRegex,
                                    })
                                    onApply(generatedRegex)
                                    onClose()
                                }}
                                tooltip="Apply"
                                icon={<IconPlus />}
                            >
                                Apply
                            </LemonButton>
                        )}
                    </div>

                    {error && <LemonBanner type="error">{error}</LemonBanner>}
                </div>
            </LemonModal>
        </>
    )
}

export function AiRegexHelperButton(): JSX.Element {
    const { setIsOpen } = useActions(aiRegexHelperLogic)

    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<IconAI />}
            onClick={() => {
                setIsOpen(true)
                posthog.capture('ai_regex_helper_open')
            }}
        >
            Help me with Regex
        </LemonButton>
    )
}
