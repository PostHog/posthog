/**
 * @fileoverview A component that helps you to generate regex for your settings using Max AI
 */

import { IconAI, IconCopy, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
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

    return (
        <>
            <LemonModal isOpen={isOpen} onClose={onClose} title="Max AI Regex Helper">
                Explain your regex in natural language:
                <LemonTextArea
                    placeholder="I want an regex that covers all urls that include 'app.posthog.com/auth/*'"
                    className="w-full my-2"
                    maxRows={4}
                    minRows={2}
                    value={input}
                    onChange={(value) => setInput(value)}
                />
                <div className="flex justify-end mt-2 gap-2">
                    {!generatedRegex && (
                        <LemonButton type="secondary" onClick={onClose} tooltip="Close">
                            Cancel
                        </LemonButton>
                    )}

                    <AIConsentPopoverWrapper>
                        <LemonButton
                            type={generatedRegex ? 'secondary' : 'primary'}
                            onClick={handleGenerateRegex}
                            disabledReason={
                                !aiAvailable
                                    ? 'To use AI features, set environment variable OPENAI_API_KEY for this instance of PostHog'
                                    : !dataProcessingAccepted
                                    ? dataProcessingApprovalDisabledReason ||
                                      'You must accept the data processing agreement to use AI features'
                                    : isLoading
                                    ? 'Generating...'
                                    : !input.length
                                    ? 'Provide a prompt first'
                                    : null
                            }
                            loading={isLoading}
                        >
                            {generatedRegex ? 'Regenerate' : 'Generate Regex'}
                        </LemonButton>
                    </AIConsentPopoverWrapper>
                </div>
                {generatedRegex && (
                    <div className="mt-2">
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
                        <div className="flex flex-row gap-2 justify-end mt-2">
                            <LemonButton type="secondary" onClick={onClose} tooltip="Close">
                                Cancel
                            </LemonButton>
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
                        </div>
                    </div>
                )}
                {error && (
                    <LemonBanner type="error" className="mt-2">
                        {error}
                    </LemonBanner>
                )}
            </LemonModal>
        </>
    )
}

export function AiRegexHelperButton(): JSX.Element {
    const { setIsOpen } = useActions(aiRegexHelperLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    const disabledReason = !dataProcessingAccepted
        ? dataProcessingApprovalDisabledReason || 'You must accept the data processing agreement to use AI features'
        : null

    return (
        <AIConsentPopoverWrapper showArrow>
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconAI />}
                onClick={() => {
                    setIsOpen(true)
                    posthog.capture('ai_regex_helper_open')
                }}
                disabledReason={disabledReason}
            >
                Help me with Regex
            </LemonButton>
        </AIConsentPopoverWrapper>
    )
}
