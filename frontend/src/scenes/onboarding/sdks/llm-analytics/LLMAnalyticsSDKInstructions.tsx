import { useValues } from 'kea'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SDKInstructionsMap, SDKKey } from '~/types'

import { renderContentItem } from '../renderOnboardingSteps'
import anthropicSpec from './stepped-instructions/llma-anthropic-installation.json'
import googleGeminiSpec from './stepped-instructions/llma-google-gemini-installation.json'
import langchainSpec from './stepped-instructions/llma-langchain-installation.json'
import litellmSpec from './stepped-instructions/llma-litellm-installation.json'
import manualCaptureSpec from './stepped-instructions/llma-manual-capture-installation.json'
import openaiSpec from './stepped-instructions/llma-open-ai-installation.json'
import openrouterSpec from './stepped-instructions/llma-openrouter-installation.json'
import vercelAiSpec from './stepped-instructions/llma-vercel-ai-installation.json'

function createInstructionsFromSpec(installationSpec: any): () => JSX.Element {
    return function InstructionsFromSpec(): JSX.Element {
        const { currentTeam } = useValues(teamLogic)
        const { isDarkModeOn } = useValues(themeLogic)
        const apiToken = currentTeam?.api_token

        if (!installationSpec.steps || installationSpec.steps.length === 0) {
            return <div>Instructions coming soon...</div>
        }

        return (
            <>
                {installationSpec.steps
                    .map((step: any, stepIndex: number) => {
                        const badge = 'badge' in step ? step.badge : null
                        const subtitle = 'subtitle' in step ? step.subtitle : null
                        const stepNumber = stepIndex + 1

                        // Handle tabbed steps
                        if (step.type === 'tabbed' && step.tabs) {
                            // Process tabs: handle platform-specific content (app/docs)
                            const processedTabs = step.tabs
                                .map((tab: any) => {
                                    let tabContent: any[] = []
                                    if (tab.content?.app) {
                                        tabContent = tab.content.app
                                    } else if (Array.isArray(tab.content)) {
                                        tabContent = tab.content
                                    }
                                    return { ...tab, content: tabContent }
                                })
                                .filter((tab: any) => tab.content.length > 0)

                            // Omit step if no tabs have content for app
                            if (processedTabs.length === 0) {
                                return null
                            }

                            return (
                                <div key={stepIndex} className="mb-8">
                                    <div className="flex items-baseline gap-2 mb-2">
                                        <h3 className="m-0">
                                            {stepNumber}. {step.title}
                                        </h3>
                                        {badge && (
                                            <LemonTag
                                                type={
                                                    badge === 'required'
                                                        ? 'highlight'
                                                        : badge === 'checkpoint'
                                                          ? 'success'
                                                          : 'default'
                                                }
                                            >
                                                {badge}
                                            </LemonTag>
                                        )}
                                    </div>
                                    {subtitle && <p className="text-muted mb-4">{subtitle}</p>}

                                    {renderContentItem(
                                        { type: 'tabbed', tabs: processedTabs } as any,
                                        stepIndex,
                                        apiToken,
                                        isDarkModeOn
                                    )}
                                </div>
                            )
                        }

                        // Handle content: can be array, or object with .app
                        // Only use .app if it exists, never fallback to .docs
                        let contentItems: any[] = []
                        if (step.content?.app) {
                            // Only use app content, never docs
                            contentItems = step.content.app
                        } else if (Array.isArray(step.content)) {
                            contentItems = step.content
                        }

                        // Omit step if content would be empty for app
                        if (contentItems.length === 0) {
                            return null
                        }

                        return (
                            <div key={stepIndex} className="mb-8">
                                <div className="flex items-baseline gap-2 mb-2">
                                    <h3 className="m-0">
                                        {stepNumber}. {step.title}
                                    </h3>
                                    {badge && (
                                        <LemonTag
                                            type={
                                                badge === 'required'
                                                    ? 'highlight'
                                                    : badge === 'checkpoint'
                                                      ? 'success'
                                                      : 'default'
                                            }
                                        >
                                            {badge}
                                        </LemonTag>
                                    )}
                                </div>
                                {subtitle && <p className="text-muted mb-4">{subtitle}</p>}

                                <div className="deprecated-space-y-4">
                                    {contentItems
                                        .map((item: any, itemIndex: number) =>
                                            renderContentItem(item as any, itemIndex, apiToken, isDarkModeOn)
                                        )
                                        .filter(Boolean)}
                                </div>
                            </div>
                        )
                    })
                    .filter(Boolean)}
            </>
        )
    }
}

export const LLMAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENAI]: createInstructionsFromSpec(openaiSpec),
    [SDKKey.ANTHROPIC]: createInstructionsFromSpec(anthropicSpec),
    [SDKKey.GOOGLE_GEMINI]: createInstructionsFromSpec(googleGeminiSpec),
    [SDKKey.VERCEL_AI]: createInstructionsFromSpec(vercelAiSpec),
    [SDKKey.LANGCHAIN]: createInstructionsFromSpec(langchainSpec),
    [SDKKey.LITELLM]: createInstructionsFromSpec(litellmSpec),
    [SDKKey.OPENROUTER]: createInstructionsFromSpec(openrouterSpec),
    [SDKKey.MANUAL_CAPTURE]: createInstructionsFromSpec(manualCaptureSpec),
}
