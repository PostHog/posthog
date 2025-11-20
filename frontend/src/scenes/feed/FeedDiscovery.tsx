import { useActions } from 'kea'
import { useState } from 'react'

import { IconDashboard, IconPlaylist, IconSparkles, IconTrends } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

const DISCOVERY_PROMPTS = [
    {
        title: 'Create a new insight',
        subtitle: 'Try something like "show me user signups over the last 30 days"',
        placeholder: 'e.g., "Show me user signups over the last 30 days"',
        promptPrefix: 'Create an insight to ',
        icon: <IconTrends />,
        hasInput: true,
        buttonText: 'Ask AI',
    },
    {
        title: 'Summarize my recent session recordings',
        subtitle: 'PostHog AI will watch your session recordings and summarize them for you',
        placeholder: 'Summarize my session recordings',
        promptPrefix: '',
        icon: <IconPlaylist />,
        hasInput: false,
        buttonText: 'Summarize my sessions!',
    },
    {
        title: 'Create a new dashboard',
        subtitle: 'Ask Posthog AI to create a new dashboard for you',
        placeholder: 'e.g., "key metrics for our mobile app"',
        promptPrefix: 'Create a new dashboard to show me ',
        icon: <IconDashboard />,
        hasInput: true,
        buttonText: 'Ask AI',
    },
]

export function FeedDiscovery(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const [inputs, setInputs] = useState<Record<number, string>>({})

    const handleSubmit = (index: number, promptPrefix: string, placeholder: string): void => {
        const userInput = inputs[index] || ''
        const promptText = userInput.trim() || placeholder
        const fullPrompt = promptPrefix + promptText
        openSidePanel(SidePanelTab.Max, fullPrompt)
    }

    return (
        <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
                <IconSparkles className="text-lg" style={{ color: '#F7B955' }} />
                <h2 className="text-lg font-semibold mb-0">Discovery</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {DISCOVERY_PROMPTS.map((item, index) => (
                    <LemonCard key={index} className="flex flex-col h-full">
                        <div className="flex items-start gap-3 mb-4">
                            <div className="flex-shrink-0 text-2xl">{item.icon}</div>
                            <div className="flex-1">
                                <h3 className="font-semibold text-base mb-1">{item.title}</h3>
                                <p className="text-xs text-muted mb-0">{item.subtitle}</p>
                            </div>
                        </div>
                        <div className="mt-auto">
                            {item.hasInput ? (
                                <div className="flex gap-2">
                                    <LemonInput
                                        value={inputs[index] || ''}
                                        onChange={(value) => setInputs({ ...inputs, [index]: value })}
                                        placeholder={item.placeholder}
                                        onPressEnter={() => handleSubmit(index, item.promptPrefix, item.placeholder)}
                                        className="flex-1"
                                    />
                                    <LemonButton
                                        type="primary"
                                        onClick={() => handleSubmit(index, item.promptPrefix, item.placeholder)}
                                    >
                                        {item.buttonText}
                                    </LemonButton>
                                </div>
                            ) : (
                                <LemonButton
                                    type="primary"
                                    onClick={() => handleSubmit(index, item.promptPrefix, item.placeholder)}
                                    fullWidth
                                >
                                    {item.buttonText}
                                </LemonButton>
                            )}
                        </div>
                    </LemonCard>
                ))}
            </div>
        </div>
    )
}
