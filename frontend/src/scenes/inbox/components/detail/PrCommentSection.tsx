import { useActions, useValues } from 'kea'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { TaskRunStatusDot } from 'products/posthog_ai/frontend/api/primitives'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import { PrCommentResponseStatusEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

/** Human-readable line for the live PR-run indicator, keyed off the run's TaskRun status. */
function prRunStatusLabel(status: string): string {
    switch (status) {
        case TaskRunStatus.COMPLETED:
            return 'The agent addressed your comment'
        case TaskRunStatus.FAILED:
            return 'The run failed while addressing your comment'
        case TaskRunStatus.CANCELLED:
            return 'The run was cancelled'
        case TaskRunStatus.IN_PROGRESS:
            return 'The agent is addressing your comment…'
        default:
            return 'Queued to address your comment'
    }
}

/**
 * "Comment on PR" affordance for a report whose implementation PR exists: a textarea that posts the
 * comment to the PR and kicks off (or feeds into) the run that addresses it, plus a live indicator for
 * that shared run. When the account isn't connected to GitHub yet, the response asks the user to connect
 * instead of dead-ending. Only rendered when the report has an `implementation_pr_url`.
 */
export function PrCommentSection({ report }: { report: SignalReport }): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { prCommentDraft, prCommentResponse, prCommentResponseLoading, prActiveRun } = useValues(logic)
    const { setPrCommentDraft, submitPrComment } = useActions(logic)

    const submit = (): void => {
        const trimmed = prCommentDraft.trim()
        if (!trimmed) {
            return
        }
        submitPrComment({ content: trimmed })
    }

    const needsConnect =
        prCommentResponse?.status === PrCommentResponseStatusEnumApi.ConnectRequired && !!prCommentResponse.connect_url

    return (
        <DetailSection icon={<IconMessage />} title="Comment on PR">
            <div className="flex flex-col gap-2">
                <LemonTextArea
                    value={prCommentDraft}
                    onChange={setPrCommentDraft}
                    placeholder="Ask for a change, or reply to the PR discussion. The agent will address it and push commits as you."
                    maxLength={10000}
                    rows={3}
                    disabled={prCommentResponseLoading}
                />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={submit}
                        loading={prCommentResponseLoading}
                        disabledReason={prCommentDraft.trim() ? undefined : 'Write a comment first'}
                    >
                        Comment
                    </LemonButton>
                </div>

                {needsConnect && prCommentResponse?.connect_url && (
                    <div className="flex flex-col gap-2 rounded border border-primary bg-surface-primary px-3 py-2.5 text-xs text-secondary leading-snug">
                        <span>Connect your GitHub account to PostHog so I can push changes as you.</span>
                        <div>
                            <LemonButton type="secondary" size="xsmall" to={prCommentResponse.connect_url} targetBlank>
                                Connect GitHub
                            </LemonButton>
                        </div>
                    </div>
                )}

                {prActiveRun && (
                    <div className="flex items-center gap-2 text-xs text-secondary">
                        <TaskRunStatusDot status={prActiveRun.status as TaskRunStatus} />
                        <span>{prRunStatusLabel(prActiveRun.status)}</span>
                    </div>
                )}
            </div>
        </DetailSection>
    )
}
