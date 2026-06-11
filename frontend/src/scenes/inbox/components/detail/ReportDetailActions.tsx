import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChat, IconChevronDown, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'

const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform)

/**
 * Should the Create PR action be offered? Mirrors desktop `canCreateImplementationPr` /
 * the server-side autostart rules: only when ready & actionable, or blocked on user input.
 */
function canCreateImplementationPr(report: SignalReport): boolean {
    if (report.implementation_pr_url) {
        return false
    }
    if (report.already_addressed === true) {
        return false
    }
    if (report.status === 'pending_input') {
        return true
    }
    if (report.status === 'ready') {
        return report.actionability === 'immediately_actionable' || report.actionability === 'requires_human_input'
    }
    return false
}

/**
 * Detail-pane actions: Discuss (opens a task with an optional question) and Create PR
 * (opens an implementation task). Both create a cloud task and navigate to it — this is NOT
 * an in-app chat thread, so both are ported (not stubbed). Task creation/navigation is owned
 * by `inboxTaskKickoffLogic`.
 */
export function ReportDetailActions({ report }: { report: SignalReport }): JSX.Element {
    const { isDiscussing, isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const { discussReport, createPrFromReport } = useActions(inboxTaskKickoffLogic)

    const showCreatePr = canCreateImplementationPr(report)
    const [discussOpen, setDiscussOpen] = useState(false)
    const [question, setQuestion] = useState('')

    const submitDiscuss = (): void => {
        const trimmed = question.trim()
        if (!trimmed) {
            return
        }
        setQuestion('')
        setDiscussOpen(false)
        discussReport(report, trimmed)
    }

    return (
        <>
            <LemonDropdown
                visible={discussOpen}
                onClickOutside={() => {
                    setDiscussOpen(false)
                    setQuestion('')
                }}
                placement="bottom-end"
                overlay={
                    <div className="flex flex-col gap-2 w-100 p-1">
                        <LemonTextArea
                            autoFocus
                            placeholder="Ask about this report…"
                            minRows={5}
                            value={question}
                            onChange={setQuestion}
                            onPressCmdEnter={submitDiscuss}
                        />
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-muted">{isMac ? '⌘↵' : 'Ctrl+↵'} to send</span>
                            <div className="flex gap-2">
                                <LemonButton
                                    size="small"
                                    onClick={() => {
                                        setDiscussOpen(false)
                                        setQuestion('')
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    disabledReason={question.trim().length === 0 ? 'Enter a question first' : undefined}
                                    onClick={submitDiscuss}
                                >
                                    Discuss
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                }
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconChat />}
                    sideIcon={<IconChevronDown />}
                    loading={isDiscussing}
                    tooltip="Discuss this report with your agent"
                    onClick={() => setDiscussOpen((open) => !open)}
                >
                    Discuss
                </LemonButton>
            </LemonDropdown>

            {showCreatePr && (
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPullRequest />}
                    loading={isCreatingPr}
                    tooltip="Have Self-driving open a pull request for this report"
                    onClick={() => createPrFromReport(report)}
                >
                    Create PR
                </LemonButton>
            )}
        </>
    )
}
