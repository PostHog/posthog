import { useActions } from 'kea'

import { IconBook, IconGraduationCap, IconLogomark, IconSparkles, IconTerminal } from '@posthog/icons'

import { IconSlack } from 'lib/lemon-ui/icons'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { quickstartLogic } from '../quickstartLogic'
import { SectionHeader } from '../shared/SectionHeader'
import { LearnCard } from './LearnCard'
import { PublicationsSection } from './PublicationsSection'
import { SubsectionHeader } from './SubsectionHeader'

export function QuickstartGuidesSection(): JSX.Element {
    const { openCompanionSetup } = useActions(quickstartLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <section>
            <SectionHeader
                title="Guides, Products, and publications"
                subtitle="Open setup guides, configure Slack or MCP, install PostHog Desktop, and read recent publications."
            />
            <div className="flex flex-col gap-6">
                <div>
                    <SubsectionHeader title="Documentation and tutorials" />
                    <div className="grid grid-cols-1 @3xl/main-content:grid-cols-3 gap-4">
                        <LearnCard
                            icon={<IconSparkles className="text-ai" />}
                            title="Ask PostHog AI"
                            description="Ask questions about the events and properties in this project. Example questions:"
                            buttonLabel="Ask PostHog AI"
                            onClick={() => openSidePanel(SidePanelTab.Max)}
                            action="ask_posthog_ai"
                            quickLinks={[
                                'What are my most visited pages this week?',
                                'How many daily active users this week?',
                                'Where do users drop off in my app?',
                            ].map((question) => ({
                                label: question,
                                // The ! prefix makes the side panel submit the question right away
                                onClick: () => openSidePanel(SidePanelTab.Max, `!${question}`),
                            }))}
                        />
                        <LearnCard
                            icon={<IconBook />}
                            title="Documentation"
                            description="Reference guides for Tools, SDKs, frameworks, and configuration:"
                            buttonLabel="Browse all docs"
                            to="https://posthog.com/docs"
                            targetBlank
                            action="open_docs_home"
                            quickLinks={[
                                {
                                    label: 'Capture custom events',
                                    to: 'https://posthog.com/docs/product-analytics/capture-events',
                                    targetBlank: true,
                                },
                                {
                                    label: 'Identify your users',
                                    to: 'https://posthog.com/docs/product-analytics/identify',
                                    targetBlank: true,
                                },
                                {
                                    label: 'Define actions from events',
                                    to: 'https://posthog.com/docs/data/actions',
                                    targetBlank: true,
                                },
                            ]}
                        />
                        <LearnCard
                            icon={<IconGraduationCap />}
                            title="Tutorials"
                            description="Step-by-step examples for common setups and workflows:"
                            buttonLabel="Browse all tutorials"
                            to="https://posthog.com/tutorials"
                            targetBlank
                            action="open_tutorials"
                            quickLinks={[
                                {
                                    label: 'Complete guide to event tracking',
                                    to: 'https://posthog.com/tutorials/event-tracking-guide',
                                    targetBlank: true,
                                },
                                {
                                    label: 'Understand behavior with session replays',
                                    to: 'https://posthog.com/tutorials/explore-insights-session-recordings',
                                    targetBlank: true,
                                },
                                {
                                    label: 'Track new and returning users',
                                    to: 'https://posthog.com/tutorials/track-new-returning-users',
                                    targetBlank: true,
                                },
                            ]}
                        />
                    </div>
                </div>
                <div>
                    <SubsectionHeader title="Slack, MCP, and PostHog Desktop" />
                    <div className="grid grid-cols-1 @3xl/main-content:grid-cols-3 gap-4">
                        <LearnCard
                            icon={<IconLogomark />}
                            title="PostHog Desktop"
                            description="Use context from PostHog while querying data or changing code from your editor or terminal."
                            buttonLabel="Get PostHog Desktop"
                            to="https://posthog.com/code"
                            targetBlank
                            action="open_posthog_code"
                        />
                        <LearnCard
                            icon={<IconSlack />}
                            title="Slack"
                            description="Use PostHog AI, insights, alerts, and replies from a Slack workspace."
                            buttonLabel="Set up Slack"
                            action="open_slack_app"
                            onClick={() => openCompanionSetup('slack')}
                        />
                        <LearnCard
                            icon={<IconTerminal />}
                            title="MCP"
                            description="Connect an AI assistant to context and actions in PostHog."
                            buttonLabel="Set up MCP"
                            action="open_mcp_docs"
                            onClick={() => openCompanionSetup('mcp')}
                        />
                    </div>
                </div>
                <PublicationsSection />
            </div>
        </section>
    )
}
