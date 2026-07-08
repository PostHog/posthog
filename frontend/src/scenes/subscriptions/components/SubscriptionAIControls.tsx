import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'
import type {
    AIReportQueryDiagnosticApi,
    QueryPlanStepApi,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import { subscriptionSceneLogic } from '../subscriptionSceneLogic'

function previewQueryStatusTag(d: AIReportQueryDiagnosticApi): JSX.Element {
    return d.ok === false ? (
        <LemonTag type="danger">{d.error_type || 'Failed'}</LemonTag>
    ) : (
        <LemonTag type="success">OK</LemonTag>
    )
}

/** The report markdown a preview would deliver, plus the per-step generated queries — never sent. */
function PreviewResult(): JSX.Element | null {
    const { preview } = useValues(subscriptionSceneLogic)
    const { clearPreview } = useActions(subscriptionSceneLogic)
    if (!preview) {
        return null
    }
    const diagnostics = preview.diagnostics ?? []
    return (
        <div className="flex flex-col gap-4 rounded border p-3">
            <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-secondary">
                    Preview (not delivered)
                </div>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={clearPreview}
                    data-attr="subscription-clear-preview"
                >
                    Clear preview
                </LemonButton>
            </div>
            <div className="max-h-96 overflow-auto rounded border bg-bg-light p-3">
                <LemonMarkdown>{preview.report || '_No report content was generated._'}</LemonMarkdown>
            </div>
            {diagnostics.length > 0 ? (
                <LemonCollapse
                    size="small"
                    multiple
                    panels={diagnostics.map((d, index) => ({
                        key: index,
                        header: (
                            <div className="flex items-center gap-2">
                                {previewQueryStatusTag(d)}
                                <span>{d.description || 'Query'}</span>
                            </div>
                        ),
                        content: d.hogql ? (
                            <CodeSnippet language={Language.SQL} compact>
                                {d.hogql}
                            </CodeSnippet>
                        ) : (
                            <span className="text-secondary">No query captured.</span>
                        ),
                    }))}
                />
            ) : null}
        </div>
    )
}

/** View + edit the frozen query plan: each step's description (read-only) and HogQL (editable textarea). */
function FrozenQueryPlanEditor({ steps }: { steps: QueryPlanStepApi[] }): JSX.Element {
    const { queryPlanEdits, hasQueryPlanEdits, subscriptionLoading } = useValues(subscriptionSceneLogic)
    const { setQueryPlanStepHogql, resetQueryPlanEdits, saveQueryPlan } = useActions(subscriptionSceneLogic)

    return (
        <div className="flex flex-col gap-3">
            <LemonCollapse
                size="small"
                multiple
                panels={steps.map((step, index) => ({
                    key: index,
                    header: <span>{step.description || `Query ${index + 1}`}</span>,
                    content: (
                        <LemonTextArea
                            className="font-mono text-xs"
                            value={index in queryPlanEdits ? queryPlanEdits[index] : step.hogql}
                            onChange={(value) => setQueryPlanStepHogql(index, value)}
                            minRows={3}
                            maxRows={16}
                            data-attr={`subscription-query-plan-step-${index}`}
                        />
                    ),
                }))}
            />
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={saveQueryPlan}
                    loading={subscriptionLoading}
                    disabledReason={
                        !hasQueryPlanEdits ? 'Edit a query to enable saving' : subscriptionLoading ? 'Saving…' : null
                    }
                    data-attr="subscription-save-query-plan"
                >
                    Save plan
                </LemonButton>
                {hasQueryPlanEdits ? (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={resetQueryPlanEdits}
                        disabled={subscriptionLoading}
                    >
                        Discard edits
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}

/**
 * Owner controls for an AI (prompt) subscription's frozen query plan: preview what would be delivered
 * (without sending), re-plan from the prompt (clearing the frozen plan), and view/edit the frozen queries.
 */
export function SubscriptionAIControls(): JSX.Element {
    const { subscription, preview, previewLoading, replanning } = useValues(subscriptionSceneLogic)
    const { previewSubscription, replanSubscription } = useActions(subscriptionSceneLogic)

    const steps = subscription?.ai_query_plan?.steps ?? []

    const confirmReplan = (): void => {
        LemonDialog.open({
            title: 'Re-plan this report?',
            description:
                'This clears the frozen query plan, so the next report re-plans from your prompt and freezes a fresh plan. Any edits you made to the queries will be discarded.',
            primaryButton: {
                children: 'Re-plan',
                status: 'danger',
                onClick: () => replanSubscription(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-lg font-semibold">AI report plan</h2>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => previewSubscription()}
                            loading={previewLoading}
                            disabledReason={previewLoading ? 'Generating preview…' : null}
                            data-attr="subscription-preview"
                        >
                            Preview
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={confirmReplan}
                            loading={replanning}
                            disabledReason={replanning ? 'Re-planning…' : null}
                            data-attr="subscription-re-plan"
                        >
                            Re-plan
                        </LemonButton>
                    </div>
                </div>
                <p className="text-sm text-secondary m-0">
                    Preview runs the report and shows what would be delivered without sending it. Re-plan discards the
                    frozen plan so the next report is generated fresh from your prompt.
                </p>
                {preview ? <PreviewResult /> : null}
                {steps.length > 0 ? (
                    <div className="flex flex-col gap-2">
                        <div className="text-xs font-semibold uppercase tracking-wide text-secondary">
                            Frozen queries
                        </div>
                        <FrozenQueryPlanEditor steps={steps} />
                    </div>
                ) : (
                    <p className="text-sm text-secondary m-0">
                        No frozen plan yet — it is created on the first delivery. Run a preview or send a test delivery
                        to generate one.
                    </p>
                )}
            </div>
        </>
    )
}
