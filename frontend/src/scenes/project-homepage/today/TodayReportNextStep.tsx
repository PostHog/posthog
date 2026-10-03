import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import {
    IconChevronDown,
    IconClock,
    IconCode,
    IconCopy,
    IconLogomark,
    IconPullRequest,
    IconSearch,
    IconSparkles,
} from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'
import { buildReportImplementationPrompt } from 'products/signals/frontend/inbox/components/detail/buildReportImplementationPrompt'
import { IMPLEMENTATION_AGENTS } from 'products/signals/frontend/inbox/components/detail/implementationAgents'
import {
    InboxQuestionSource,
    captureInboxReportAction,
    discussQuestionProperties,
} from 'products/signals/frontend/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic, isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type { ReportTaskEntry } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { parsePrUrlParts } from 'products/signals/frontend/inbox/utils/reportPresentation'
import type { BriefingItemStateEnumApi } from 'products/today/frontend/generated/api.schemas'

import { TodayActionButton } from './TodayActionButton'
import { todayLogic } from './todayLogic'
import {
    TodayNextStep,
    buildReportInvestigationPrompt,
    inFlightPullRequest,
    pullRequestsIn,
    reportWorkKind,
    todayReportSections,
} from './todayReportPresentation'
import { isSampleReportId } from './todaySampleReports'

const AGENTS = IMPLEMENTATION_AGENTS.filter((agent) => agent.key !== 'posthog-code')
const SAMPLE_REASON = 'Sample reports can’t start work. Turn off sample reports to use a real one.'

type PrimaryAction =
    | { kind: 'review'; url: string; label: string }
    | { kind: 'open_task'; label: string }
    | { kind: 'start' }
    | null

function reviewLabel(url: string, draft: boolean): string {
    const number = parsePrUrlParts(url)?.number
    const name = draft ? 'draft PR' : 'PR'
    return number ? `Review ${name} #${number}` : `Review ${name}`
}

function pickedUp(date: string | null): string {
    return date ? ` on ${dayjs(date).format('D MMM')}` : ''
}

function withPullRequest(report: SignalReport, note: string): { primary: PrimaryAction; note: string } {
    const pullRequest = inFlightPullRequest(report)
    return {
        primary: pullRequest
            ? { kind: 'review', url: pullRequest.url, label: `View PR #${pullRequest.number}` }
            : { kind: 'start' },
        note,
    }
}

function decide(
    step: TodayNextStep,
    report: SignalReport,
    hasRun: boolean
): { primary: PrimaryAction; note: string | null } {
    switch (step.kind) {
        case 'review_pr':
            return {
                primary: { kind: 'review', url: step.url, label: reviewLabel(step.url, step.state === 'draft') },
                note:
                    step.reviewDecision === 'approved'
                        ? 'Approved and ready to merge.'
                        : step.reviewDecision === 'changes_requested'
                          ? 'A reviewer asked for changes.'
                          : null,
            }
        case 'merged':
            return { primary: null, note: 'The fix is merged. Resolve the report once it is live.' }
        case 'task_running': {
            if (hasRun) {
                return { primary: { kind: 'open_task', label: 'Open the running task' }, note: null }
            }
            return withPullRequest(report, `A PostHog task picked this up${pickedUp(step.since)}.`)
        }
        case 'claimed':
            return withPullRequest(report, `${step.by} picked this up${pickedUp(step.since)}.`)
        case 'already_addressed': {
            const pullRequest = inFlightPullRequest(report)
            return pullRequest
                ? {
                      primary: { kind: 'review', url: pullRequest.url, label: `View PR #${pullRequest.number}` },
                      note: null,
                  }
                : {
                      primary: null,
                      note:
                          pullRequestsIn(todayReportSections(report.summary).proposal, report.repo_slug).size > 0
                              ? null
                              : 'A fix is already in flight. The full report links to it.',
                  }
        }
        case 'needs_input':
        case 'start':
            return { primary: { kind: 'start' }, note: null }
    }
}

export function TodayReportNextStep({
    report,
    reportState,
    reportUrl,
    reportTaskToOpen,
    step,
}: {
    report: SignalReport
    reportState: BriefingItemStateEnumApi
    reportUrl: string
    reportTaskToOpen: ReportTaskEntry | null
    step: TodayNextStep
}): JSX.Element | null {
    const { createPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { openReportTask } = useActions(inboxTaskKickoffLogic)
    const { askingAi } = useValues(todayLogic)
    const { askAi } = useActions(todayLogic)
    const [composerOpen, setComposerOpen] = useState(false)
    const [draft, setDraft] = useState('')
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const isSample = isSampleReportId(report.id)
    const sampleReason = isSample ? SAMPLE_REASON : null
    const task = reportTaskToOpen?.task
    const run = task?.latest_run
    const { primary, note } = decide(step, report, !!(task && run))
    const workKind = reportWorkKind(report)
    const workPrompt =
        workKind === 'implement'
            ? buildReportImplementationPrompt(report, reportUrl)
            : buildReportInvestigationPrompt(report, reportUrl)

    if (reportState !== 'open') {
        return null
    }

    const askDisabledReason = isSample
        ? 'Sample reports can’t start a chat. Turn off sample reports to ask about a real one.'
        : null
    const startDisabledReason =
        sampleReason ??
        (step.kind === 'task_running' || step.kind === 'claimed' ? 'A task already picked this up.' : null) ??
        (!isActionCapableReport(report) ? 'This report can’t start work. Ask about it instead.' : null) ??
        createPrDisabledReason

    const openComposer = (text: string): void => {
        setComposerOpen(true)
        setDraft(text)
        requestAnimationFrame(() => {
            const textArea = textAreaRef.current
            textArea?.focus({ preventScroll: true })
            textArea?.setSelectionRange(text.length, text.length)
        })
    }

    const ask = (question: string, source: InboxQuestionSource): void => {
        if (!question || askDisabledReason || askingAi) {
            return
        }
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'today',
            extra: discussQuestionProperties({ source, suggestionCount: 0 }),
        })
        askAi(question, 'report_page', report)
    }

    const runPrompt = (agentKey: string, send: (prompt: string) => void): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'today',
            extra: { agent: agentKey },
        })
        send(workPrompt)
    }

    return (
        <div className="flex flex-col gap-2" data-attr="today-report-continue">
            <div className="flex flex-wrap items-center gap-1">
                {primary?.kind === 'review' && (
                    <TodayActionButton
                        variant="primary"
                        className="me-1"
                        nativeButton={false}
                        render={<LinkPrimitive to={primary.url} target="_blank" />}
                        disabledReason={sampleReason}
                        data-attr="today-report-review-pr"
                    >
                        <IconPullRequest />
                        {primary.label}
                    </TodayActionButton>
                )}
                {primary?.kind === 'open_task' && task && run && (
                    <TodayActionButton
                        variant="primary"
                        className="me-1"
                        onClick={() => openReportTask(report, task.id, run.id)}
                        data-attr="today-report-open-task"
                    >
                        <IconClock />
                        {primary.label}
                    </TodayActionButton>
                )}
                {primary?.kind === 'start' && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="primary"
                                    disabled={isSample}
                                    className="me-1 gap-1.5"
                                    data-attr="today-report-implement-with"
                                >
                                    {workKind === 'implement' ? <IconCode /> : <IconSearch />}
                                    {workKind === 'implement' ? 'Implement with' : 'Investigate with'}
                                    <IconChevronDown />
                                </Button>
                            }
                        />
                        <DropdownMenuContent align="start" className="TodayMenu w-52">
                            <DropdownMenuItem
                                onClick={() => openComposer(workPrompt)}
                                disabled={!!startDisabledReason}
                                title={startDisabledReason ?? undefined}
                                data-attr="today-report-start-task"
                            >
                                <IconLogomark className="size-4" />
                                PostHog
                            </DropdownMenuItem>
                            {AGENTS.map((agent) => (
                                <DropdownMenuItem
                                    key={agent.key}
                                    onClick={() =>
                                        runPrompt(agent.key, (prompt) =>
                                            window.open(agent.buildDeepLink(prompt), '_blank')
                                        )
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
                                    runPrompt(
                                        'clipboard',
                                        (prompt) => void copyToClipboard(prompt, 'prompt for your agent')
                                    )
                                }
                                data-attr="today-report-copy-prompt"
                            >
                                <IconCopy className="size-4" />
                                Copy prompt
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                <TodayActionButton
                    className={primary ? undefined : '-ms-2'}
                    onClick={() => openComposer(composerOpen ? draft : '')}
                    disabledReason={askDisabledReason}
                    data-attr="today-report-ask"
                >
                    <IconSparkles />
                    Ask about it
                </TodayActionButton>
            </div>
            {note && (
                <Text size="xs" render={<p />} className="flex items-center gap-1.5">
                    <IconClock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    {note}
                </Text>
            )}
            {composerOpen && (
                <Composer.Root
                    value={draft}
                    onChange={setDraft}
                    onSubmit={() => {
                        ask(draft.trim(), 'typed')
                        setDraft('')
                    }}
                    textAreaRef={textAreaRef}
                    disabledReason={askDisabledReason ?? undefined}
                    loading={askingAi}
                    disabled={askingAi}
                >
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>Ask PostHog AI about this report</Composer.Placeholder>
                            <Composer.Textarea
                                maxRows={6}
                                className="[mask-image:linear-gradient(to_bottom,black_calc(100%-1rem),transparent)]"
                                data-attr="today-report-prompt-input"
                            />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit data-attr="today-report-prompt-submit" />
                </Composer.Root>
            )}
        </div>
    )
}
