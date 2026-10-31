import { useValues } from 'kea'

import { IconExternal, IconLock } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { PhaiSidePanelChat } from 'scenes/max/components/PhaiSidePanelChat'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sidePanelMaxLogic } from 'scenes/max/maxLogic'

import { REPORT_AI_PANEL, SCOUT_AI_PANEL } from '~/layout/ai/aiPanelIds'
import { SidePanelMax } from '~/layout/navigation-3000/sidepanel/panels/max/SidePanelMax'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

export function TodayAiPanel(): JSX.Element {
    const { isMaxAvailable, effectivePhaiView } = useValues(maxGlobalLogic)
    const { selectedTabOptions } = useValues(sidePanelStateLogic)

    // Closing the panel unmounts this tree, so hold the chat logic to keep the open chat and draft.
    useOnMountEffect(() => {
        sidePanelMaxLogic()
    })

    if (!isMaxAvailable) {
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconLock />
                    </EmptyMedia>
                    <EmptyTitle>PostHog AI isn't set up yet</EmptyTitle>
                    <EmptyDescription>
                        PostHog AI runs on your own LLM provider key. Set <code>ANTHROPIC_API_KEY</code> for this
                        instance and restart PostHog to start chatting.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        render={
                            // eslint-disable-next-line react/forbid-elements
                            <a
                                href="https://posthog.com/docs/self-host/configure/environment-variables?utm_medium=in-product&utm_campaign=max-not-configured"
                                target="_blank"
                                rel="noopener noreferrer"
                                data-attr="max-not-configured-configure-key"
                            />
                        }
                    >
                        Configuring environment variables
                        <IconExternal />
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    // The legacy chat, and the report and scout chats, keep their own panels until they move to the runner.
    if (
        effectivePhaiView === 'legacy' ||
        selectedTabOptions === REPORT_AI_PANEL ||
        selectedTabOptions === SCOUT_AI_PANEL
    ) {
        return <SidePanelMax header={null} />
    }

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <PhaiSidePanelChat />
        </div>
    )
}
