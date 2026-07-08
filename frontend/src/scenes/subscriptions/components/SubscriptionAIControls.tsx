import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import { subscriptionSceneLogic } from '../subscriptionSceneLogic'
import type { QueryPlanStep } from '../subscriptionSceneLogic'
import { GeneratedQueries } from './SubscriptionAiReportDelivery'

/** The report a preview run produced, plus its per-step generated queries — rendered from the preview's
 * delivery row (same shape the history viewer uses), never sent to recipients. */
function PreviewResult(): JSX.Element | null {
    const { preview } = useValues(subscriptionSceneLogic)
    const { clearPreview } = useActions(subscriptionSceneLogic)
    if (!preview) {
        return null
    }
    const diagnostics = preview.ai_report_diagnostics ?? []
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
                <LemonMarkdown>{preview.ai_report || '_No report content was generated._'}</LemonMarkdown>
            </div>
            {diagnostics.length > 0 ? <GeneratedQueries diagnostics={diagnostics} /> : null}
        </div>
    )
}

/** View + edit the frozen query plan: each step's description (read-only) and HogQL (editable textarea). */
function FrozenQueryPlanEditor({ steps }: { steps: QueryPlanStep[] }): JSX.Element {
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
                            aria-label={`HogQL for step ${index + 1}: ${step.description || 'query'}`}
                            value={queryPlanEdits[index] !== undefined ? queryPlanEdits[index] : step.hogql}
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
 * (without sending), regenerate the plan from the prompt (clearing the frozen one), and view/edit the
 * frozen queries.
 */
export function SubscriptionAIControls(): JSX.Element {
    const { subscription, preview, previewLoading, subscriptionLoading } = useValues(subscriptionSceneLogic)
    const { previewSubscription, regeneratePlan } = useActions(subscriptionSceneLogic)

    const steps = subscription?.ai_query_plan?.steps ?? []

    const confirmRegenerate = (): void => {
        LemonDialog.open({
            title: 'Regenerate the query plan?',
            description:
                'This clears the frozen query plan, so the next report re-plans from your prompt and freezes a fresh plan. Any edits you made to the queries will be discarded.',
            primaryButton: {
                children: 'Regenerate plan',
                status: 'danger',
                onClick: () => regeneratePlan(),
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
                            onClick={confirmRegenerate}
                            loading={subscriptionLoading}
                            disabledReason={subscriptionLoading ? 'Working…' : null}
                            data-attr="subscription-regenerate-plan"
                        >
                            Regenerate plan
                        </LemonButton>
                    </div>
                </div>
                <p className="text-sm text-secondary m-0">
                    Preview generates the report in the background and shows what would be delivered without sending it
                    (this can take a couple of minutes). Regenerate plan discards the frozen plan so the next report is
                    planned fresh from your prompt.
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
                        No frozen plan yet — it is created on the first delivery. Send a test delivery to generate one.
                    </p>
                )}
            </div>
        </>
    )
}
