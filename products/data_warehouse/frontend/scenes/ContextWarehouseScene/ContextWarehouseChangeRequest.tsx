import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

type PreviewDecision = 'pending' | 'changes-requested' | 'approved'

type ContextWarehouseChangeRequestProps = {
    summary: string
    reason: string
    validationItems: string[]
    originalQuery: string
    proposedQuery: string
    reviewerNote: string
    decision: PreviewDecision
    onReviewerNoteChange: (value: string) => void
    onDecisionChange: (decision: PreviewDecision) => void
}

export function ContextWarehouseChangeRequest({
    summary,
    reason,
    validationItems,
    originalQuery,
    proposedQuery,
    reviewerNote,
    decision,
    onReviewerNoteChange,
    onDecisionChange,
}: ContextWarehouseChangeRequestProps): JSX.Element {
    return (
        <div className="@container/context-warehouse-change space-y-4">
            <LemonBanner type="warning">
                Concept preview. Warehouse change requests are not available. These actions only update this Storybook
                story.
            </LemonBanner>

            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <h2 className="mb-0">Proposed warehouse change</h2>
                    <LemonTag type="warning">Needs review</LemonTag>
                </div>
                {decision === 'changes-requested' ? (
                    <LemonTag type="warning">Changes requested in preview</LemonTag>
                ) : decision === 'approved' ? (
                    <LemonTag type="success">Approved in preview</LemonTag>
                ) : (
                    <LemonTag>Preview decision pending</LemonTag>
                )}
            </div>

            <div className="grid grid-cols-1 gap-4 @min-[48rem]/context-warehouse-change:grid-cols-[minmax(0,2fr)_minmax(16rem,1fr)]">
                <LemonCard className="space-y-4 p-4" hoverEffect={false}>
                    <div>
                        <h3 className="mb-1 text-sm font-semibold">Summary</h3>
                        <p className="mb-0 text-sm">{summary}</p>
                    </div>
                    <div>
                        <h3 className="mb-1 text-sm font-semibold">Reason</h3>
                        <p className="mb-0 text-sm text-secondary">{reason}</p>
                    </div>
                    <div>
                        <h3 className="mb-2 text-sm font-semibold">Proposed SQL</h3>
                        <div className="h-80 overflow-hidden rounded border">
                            <CodeEditor
                                height="100%"
                                language="sql"
                                originalValue={originalQuery}
                                options={{
                                    fontSize: 13,
                                    minimap: { enabled: false },
                                    readOnly: true,
                                    scrollBeyondLastLine: false,
                                    wordWrap: 'on',
                                }}
                                value={proposedQuery}
                            />
                        </div>
                    </div>
                </LemonCard>

                <div className="space-y-4">
                    <LemonCard className="p-4" hoverEffect={false}>
                        <h3 className="mb-3 text-sm font-semibold">Validation</h3>
                        <ul className="m-0 list-none space-y-2 p-0">
                            {validationItems.map((item) => (
                                <li key={item} className="flex items-start gap-2 text-sm">
                                    <IconCheck className="mt-0.5 shrink-0 text-success" />
                                    <span>{item}</span>
                                </li>
                            ))}
                        </ul>
                    </LemonCard>

                    <LemonCard className="space-y-3 p-4" hoverEffect={false}>
                        <div>
                            <h3 className="mb-1 text-sm font-semibold">Reviewer note</h3>
                            <p className="mb-0 text-xs text-secondary">This note stays in this Storybook preview.</p>
                        </div>
                        <LemonTextArea
                            aria-label="Reviewer note"
                            data-attr="context-warehouse-reviewer-note"
                            minRows={4}
                            onChange={onReviewerNoteChange}
                            placeholder="Add feedback for the proposed change"
                            value={reviewerNote}
                        />
                        <div className="flex flex-wrap justify-end gap-2">
                            <LemonButton
                                data-attr="context-warehouse-request-changes"
                                onClick={() => onDecisionChange('changes-requested')}
                                type="secondary"
                            >
                                Request changes
                            </LemonButton>
                            <LemonButton
                                data-attr="context-warehouse-approve-change"
                                onClick={() => onDecisionChange('approved')}
                                type="primary"
                            >
                                Approve change
                            </LemonButton>
                        </div>
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}
