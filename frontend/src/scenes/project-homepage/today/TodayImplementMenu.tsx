import { IconChevronDown, IconCode, IconCopy, IconLogomark, IconSearch } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { IMPLEMENTATION_AGENTS } from 'products/signals/frontend/inbox/components/detail/implementationAgents'
import { captureInboxReportAction } from 'products/signals/frontend/inbox/inboxAnalytics'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { reportWorkKind, reportWorkPrompt } from './todayNextStep'

const AGENTS = IMPLEMENTATION_AGENTS.filter((agent) => agent.key !== 'posthog-code')

export function TodayImplementMenu({
    report,
    reportUrl,
    disabled,
    postHogDisabledReason,
    onStartWithPostHog,
}: {
    report: SignalReport
    reportUrl: string
    disabled: boolean
    postHogDisabledReason: string | null
    onStartWithPostHog: (prompt: string) => void
}): JSX.Element {
    const implement = reportWorkKind(report) === 'implement'

    const sendPrompt = (agentKey: string, send: (prompt: string) => void): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'today',
            extra: { agent: agentKey },
        })
        send(reportWorkPrompt(report, reportUrl))
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="primary"
                        disabled={disabled}
                        className="me-1 gap-1.5"
                        data-attr="today-report-implement-with"
                    >
                        {implement ? <IconCode /> : <IconSearch />}
                        {implement ? 'Implement with' : 'Investigate with'}
                        <IconChevronDown />
                    </Button>
                }
            />
            <DropdownMenuContent align="start" className="TodayImplementMenu w-52">
                <DropdownMenuItem
                    onClick={() => onStartWithPostHog(reportWorkPrompt(report, reportUrl))}
                    disabled={!!postHogDisabledReason}
                    title={postHogDisabledReason ?? undefined}
                    data-attr="today-report-start-task"
                >
                    <IconLogomark className="size-4" />
                    PostHog
                </DropdownMenuItem>
                {AGENTS.map((agent) => (
                    <DropdownMenuItem
                        key={agent.key}
                        onClick={() =>
                            sendPrompt(agent.key, (prompt) => window.open(agent.buildDeepLink(prompt), '_blank'))
                        }
                        data-attr={`today-report-open-${agent.key}`}
                    >
                        {agent.icon}
                        {agent.name}
                    </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    onClick={() =>
                        sendPrompt('clipboard', (prompt) => void copyToClipboard(prompt, 'prompt for your agent'))
                    }
                    data-attr="today-report-copy-prompt"
                >
                    <IconCopy className="size-4" />
                    Copy prompt
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
