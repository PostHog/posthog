import { useActions, useValues } from 'kea'

import { IconBell, IconEllipsis, IconRefresh, IconSparkles, IconSupport } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { healthSceneLogic } from './healthSceneLogic'
import { buildHealthOverviewPrompt, HEALTH_OVERVIEW_QUESTIONS } from './healthUtils'

export interface QuillHealthSceneActionsProps {
    askAiEnabled: boolean
    refreshTooltip: string
    cooldownLabel: string | undefined
}

export function QuillHealthSceneActions({
    askAiEnabled,
    refreshTooltip,
    cooldownLabel,
}: QuillHealthSceneActionsProps): JSX.Element {
    const { showDismissed, healthIssuesLoading, isRefreshInFlight, issues } = useValues(healthSceneLogic)
    const { refreshHealthData, setShowDismissed } = useActions(healthSceneLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                variant="outline"
                render={<LinkPrimitive to={urls.healthAlerts()} />}
                tooltip="Subscribe to alerts when any health check fires"
            >
                <IconBell />
                Alerts
            </Button>

            {askAiEnabled && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button variant="outline" tooltip="Ask PostHog AI about your health issues" />}
                    >
                        <IconSparkles />
                        Ask PostHog AI
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-56">
                        {HEALTH_OVERVIEW_QUESTIONS.map((question) => (
                            <DropdownMenuItem
                                key={question}
                                onClick={() =>
                                    openSidePanel(SidePanelTab.Max, `!${buildHealthOverviewPrompt(issues, question)}`)
                                }
                            >
                                {question}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            <Button variant="outline" onClick={() => openSupportForm({ kind: 'support' })}>
                <IconSupport />
                Get help from our team
            </Button>
            <Button
                size="icon"
                aria-label={refreshTooltip}
                tooltip={refreshTooltip}
                loading={isRefreshInFlight || healthIssuesLoading}
                disabledReason={cooldownLabel}
                onClick={() => refreshHealthData()}
            >
                <IconRefresh />
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button size="icon" aria-label="More options" tooltip="More options" />}>
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuCheckboxItem checked={showDismissed} onCheckedChange={setShowDismissed}>
                        Show dismissed
                    </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
