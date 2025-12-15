import { useActions } from 'kea'
import { useState } from 'react'

import { IconDashboard, IconPlaylist, IconSparkles, IconTrends } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

const DISCOVERY_PROMPTS = [
    // TODO: Abe to add "teams like yours" card
    {
        title: 'Create a new insight',
        subtitle: 'Try something like "show me user signups over the last 30 days"',
        placeholder: 'e.g., "Show me user signups over the last 30 days"',
        promptPrefix: 'Create an insight: ',
        icon: <IconTrends style={{ color: '#1D4AFF' }} />,
        hasInput: true,
        buttonText: 'Ask PostHog AI',
        dataAttr: 'feed-discovery-create-insight',
    },
    {
        title: 'Summarize my recent session recordings',
        subtitle: 'PostHog AI will watch your session recordings and summarize them for you',
        placeholder: 'Summarize my session recordings',
        promptPrefix: '',
        icon: <IconPlaylist style={{ color: '#B62AD9' }} />,
        hasInput: false,
        buttonText: 'Summarize my sessions!',
        dataAttr: 'feed-discovery-summarize-sessions',
    },
    {
        title: 'Create a new dashboard',
        subtitle: 'Ask PostHog AI to create a new dashboard for you',
        placeholder: 'e.g., "key metrics for our mobile app"',
        promptPrefix: 'Create a new dashboard: ',
        icon: <IconDashboard style={{ color: '#36B37E' }} />,
        hasInput: true,
        buttonText: 'Ask PostHog AI',
        dataAttr: 'feed-discovery-create-dashboard',
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
                <h2 className="text-lg font-semibold mb-0">Discover</h2>
            </div>
            <ScrollableShadows direction="horizontal" className="py-1" innerClassName="flex gap-4" styledScrollbars>
                {DISCOVERY_PROMPTS.map((item, index) => (
                    <LemonCard key={index} className="flex flex-col h-full w-[380px] flex-shrink-0">
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
                                        center={true}
                                        onClick={() => handleSubmit(index, item.promptPrefix, item.placeholder)}
                                        data-attr={item.dataAttr}
                                    >
                                        {item.buttonText}
                                    </LemonButton>
                                </div>
                            ) : (
                                <LemonButton
                                    type="primary"
                                    center={true}
                                    onClick={() => handleSubmit(index, item.promptPrefix, item.placeholder)}
                                    fullWidth
                                    data-attr={item.dataAttr}
                                >
                                    <div className="flex items-center gap-2 justify-center">
                                        <IconSparkles className="text-base" />
                                        {item.buttonText}
                                    </div>
                                </LemonButton>
                            )}
                        </div>
                    </LemonCard>
                ))}
            </ScrollableShadows>
        </div>
    )
}
