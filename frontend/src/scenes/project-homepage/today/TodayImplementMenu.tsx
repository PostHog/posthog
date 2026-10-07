import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconCode, IconCopy, IconLogomark, IconSearch } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, Text } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DROPDOWN_PARTS, SHEET_PARTS, TodayMenuParts } from '~/layout/today/todayMenuParts'
import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { IMPLEMENTATION_AGENTS } from 'products/signals/frontend/inbox/components/detail/implementationAgents'
import { captureInboxReportAction } from 'products/signals/frontend/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayActionButton } from './TodayActionButton'
import { reportWorkKind, reportWorkPrompt } from './todayNextStep'
import { todayReportLogic } from './todayReportLogic'

const AGENTS = IMPLEMENTATION_AGENTS.filter((agent) => agent.key !== 'posthog-code')

export function TodayImplementMenu({
    report,
    reportUrl,
    disabledReason,
    postHogDisabledReason,
}: {
    report: SignalReport
    reportUrl: string
    disabledReason: string | null
    postHogDisabledReason: string | null
}): JSX.Element {
    const { isCreatingPr, isDiscussing } = useValues(inboxTaskKickoffLogic)
    const { startWithPostHog } = useActions(todayReportLogic({ reportId: report.id }))
    const { phoneLayout } = useValues(todayShellLogic)
    const [sheetOpen, setSheetOpen] = useState(false)
    const starting = isCreatingPr || isDiscussing
    const implement = reportWorkKind(report) === 'implement'

    const sendPrompt = (agentKey: string, send: (prompt: string) => void): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'today',
            extra: { agent: agentKey, work: reportWorkKind(report) },
        })
        send(reportWorkPrompt(report, reportUrl))
    }

    const label = (
        <>
            {implement ? <IconCode /> : <IconSearch />}
            <span>{implement ? 'Implement with' : 'Investigate with'}</span>
            <IconChevronDown />
        </>
    )

    if (disabledReason) {
        return (
            <TodayActionButton
                variant="primary"
                className="me-1 gap-1.5"
                disabledReason={disabledReason}
                data-attr="today-report-implement-with"
            >
                {label}
            </TodayActionButton>
        )
    }

    const items = ({ Item, Separator }: TodayMenuParts): JSX.Element => (
        <>
            <Item
                onClick={() => startWithPostHog()}
                disabled={!!postHogDisabledReason || starting}
                dataAttr="today-report-start-task"
            >
                <IconLogomark className="size-4 self-start" />
                <span className="flex flex-col">
                    <span>PostHog</span>
                    {postHogDisabledReason && (
                        <Text size="xs" variant="muted" render={<span />}>
                            {postHogDisabledReason}
                        </Text>
                    )}
                </span>
            </Item>
            {AGENTS.map((agent) => (
                <Item
                    key={agent.key}
                    onClick={() => sendPrompt(agent.key, agent.open)}
                    dataAttr={`today-report-open-${agent.key}`}
                >
                    {agent.icon}
                    {agent.name}
                </Item>
            ))}
            <Separator />
            <Item
                onClick={() =>
                    sendPrompt('clipboard', (prompt) => void copyToClipboard(prompt, 'prompt for your agent'))
                }
                dataAttr="today-report-copy-prompt"
            >
                <IconCopy className="size-4" />
                Copy prompt
            </Item>
        </>
    )
    const trigger = (onClick?: () => void): JSX.Element => (
        <Button
            variant="primary"
            loading={starting}
            onClick={onClick}
            className="me-1 gap-1.5"
            data-attr="today-report-implement-with"
        >
            {label}
        </Button>
    )

    if (phoneLayout) {
        return (
            <>
                {trigger(() => setSheetOpen(true))}
                <TodaySheetMenu
                    open={sheetOpen}
                    onOpenChange={setSheetOpen}
                    title={implement ? 'Implement with' : 'Investigate with'}
                >
                    {items(SHEET_PARTS)}
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={trigger()} />
            <DropdownMenuContent align="start" className="TodayImplementMenu w-52">
                {items(DROPDOWN_PARTS)}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
