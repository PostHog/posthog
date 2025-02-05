/**
 * @fileoverview A component that helps you to generate regex for your settings using Max AI
 */

import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { aiRegexHelperLogic } from './aiRegexHelperLogic'

export function AiRegexHelper(): JSX.Element {
    const filterLogic = aiRegexHelperLogic()
    const { isOpen, input, generatedRegex, error, isLoading } = useValues(filterLogic)
    const { setInput, handleGenerateRegex, handleApplyRegex, onClose } = useActions(filterLogic)
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)

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
                {!dataProcessingAccepted && (
                    <div className="flex justify-center">
                        <Popover
                            overlay={
                                <div className="m-1.5">
                                    <p className="font-medium text-pretty mb-1.5">
                                        Hi! I use OpenAI services to analyze your data,
                                        <br />
                                        so that you can focus on building. This <em>can</em> include
                                        <br />
                                        personal data of your users, if you're capturing it.
                                        <br />
                                        <em>Your data won't be used for training models.</em>
                                    </p>
                                    <LemonButton type="secondary" size="small" onClick={() => acceptDataProcessing()}>
                                        Got it, I accept OpenAI processing data
                                    </LemonButton>
                                </div>
                            }
                            placement="right-end"
                            showArrow
                            visible={true}
                        >
                            <HedgehogBuddy
                                static
                                hedgehogConfig={{
                                    ...hedgehogConfig,
                                    walking_enabled: false,
                                    controls_enabled: false,
                                }}
                                onClick={(actor) => {
                                    if (Math.random() < 0.01) {
                                        actor.setOnFire()
                                    } else {
                                        actor.setRandomAnimation()
                                    }
                                }}
                                onActorLoaded={(actor) =>
                                    setTimeout(() => {
                                        actor.setAnimation('wave')
                                        // Always start out facing right so that the data processing popover is more readable
                                        actor.direction = 'right'
                                    }, 100)
                                }
                            />
                        </Popover>
                    </div>
                )}
                <div className="flex justify-center mt-2">
                    <LemonButton
                        type="primary"
                        onClick={handleGenerateRegex}
                        disabled={!input.length || isLoading || !dataProcessingAccepted}
                        loading={isLoading}
                    >
                        {generatedRegex ? 'Regenerate' : 'Generate Regex'}
                    </LemonButton>
                </div>
                {generatedRegex && (
                    <div className="mt-2">
                        Your regex is:
                        <div className="flex flex-row justify-between gap-2 items-center">
                            <LemonBanner
                                type="info"
                                className="w-full flex flex-row justify-between gap-2 items-center"
                            >
                                {generatedRegex}
                            </LemonBanner>
                            <div>
                                <LemonButton
                                    type="primary"
                                    onClick={handleApplyRegex}
                                    tooltip="Copy to clipboard"
                                    icon={<IconCopy />}
                                />
                            </div>
                        </div>
                    </div>
                )}
                {error && <LemonBanner type="error">{error}</LemonBanner>}
            </LemonModal>
        </>
    )
}
