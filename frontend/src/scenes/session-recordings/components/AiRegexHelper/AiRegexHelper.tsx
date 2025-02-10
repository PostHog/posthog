/**
 * @fileoverview A component that helps you to generate regex for your settings using Max AI
 */

import { IconCopy, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { AiConsentPopover } from '../AiConsentPopover'
import { aiRegexHelperLogic } from './aiRegexHelperLogic'

export function AiRegexHelper({ type }: { type: 'trigger' | 'blocklist' }): JSX.Element {
    const logic = aiRegexHelperLogic()
    const { isOpen, input, generatedRegex, error, isLoading } = useValues(logic)
    const { setInput, handleGenerateRegex, handleApplyRegex, onClose, handleCopyToClipboard } = useActions(logic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

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
                <AiConsentPopover />
                <div className="flex justify-end mt-2 gap-2">
                    <LemonButton type="secondary" onClick={onClose} tooltip="Close">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type={generatedRegex ? 'secondary' : 'primary'}
                        onClick={handleGenerateRegex}
                        disabled={!input.length || isLoading || !dataProcessingAccepted}
                        loading={isLoading}
                    >
                        {generatedRegex ? 'Regenerate' : 'Generate Regex'}
                    </LemonButton>
                </div>
                {generatedRegex && (
                    <div className="mt-2">
                        <h3 className="text-sm font-bold">Your regex is:</h3>
                        <LemonBanner type="info">{generatedRegex}</LemonBanner>
                        <div className="flex flex-row gap-2 justify-end mt-2">
                            <LemonButton
                                type="secondary"
                                onClick={handleCopyToClipboard}
                                tooltip="Copy to clipboard"
                                icon={<IconCopy />}
                            >
                                Copy to clipboard
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    handleApplyRegex(type)
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
