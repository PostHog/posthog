import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyCurrency, humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'
import { unitNoun } from './units'

function costText(usd: number | null): string {
    if (usd === null) {
        return 'Unknown'
    }
    return usd > 0 && usd < 0.01 ? 'Under $0.01' : humanFriendlyCurrency(usd)
}

export function JudgeSuggestionConfirmModal(): JSX.Element {
    const {
        judgeConfirm,
        judgeConfirmError,
        judgeConfirmNeedsProviderKey,
        evalSuggestionEstimate: estimate,
        evalSuggestionEstimateLoading,
        estimateError,
        inFlight,
    } = useValues(evaluationSuggestionsLogic)
    const { closeJudgeConfirm, acceptSuggestion } = useActions(evaluationSuggestionsLogic)
    const accepting = inFlight?.action === 'accept'
    const units = unitNoun(estimate?.target, 2)
    // The estimate names no model when the project has no working AI provider key, which accept would refuse.
    const needsKey = !!estimate && !estimate.judge_model

    return (
        <LemonModal
            isOpen={!!judgeConfirm}
            onClose={closeJudgeConfirm}
            closable={!accepting}
            title="Add LLM judge"
            description={judgeConfirm?.headline}
            width={480}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeJudgeConfirm}
                        disabledReason={accepting ? 'Wait until the eval is added' : null}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={accepting}
                        disabledReason={
                            evalSuggestionEstimateLoading
                                ? 'Wait for the cost estimate'
                                : needsKey
                                  ? 'Add a working AI provider key first'
                                  : null
                        }
                        onClick={() => judgeConfirm && acceptSuggestion(judgeConfirm)}
                        data-attr="eval-suggestion-confirm-add"
                    >
                        Add eval
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                {needsKey && !judgeConfirmError && (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Manage provider keys',
                            to: urls.settings('project-ai-observability', 'ai-observability-byok'),
                        }}
                    >
                        LLM judges run on your own AI provider key. Add a working key to add this eval.
                    </LemonBanner>
                )}
                {judgeConfirmError && (
                    <LemonBanner
                        type="error"
                        action={
                            judgeConfirmNeedsProviderKey
                                ? {
                                      children: 'Manage provider keys',
                                      to: urls.settings('project-ai-observability', 'ai-observability-byok'),
                                  }
                                : undefined
                        }
                    >
                        {judgeConfirmError}
                    </LemonBanner>
                )}
                {evalSuggestionEstimateLoading ? (
                    <div className="flex items-center gap-2 text-secondary">
                        <Spinner />
                        <span>Estimating the cost…</span>
                    </div>
                ) : estimateError ? (
                    <p className="m-0 text-secondary">{`${estimateError} You can still add the eval.`}</p>
                ) : estimate ? (
                    <>
                        <p className="m-0">
                            {`${
                                estimate.units > 0
                                    ? `It runs on recent ${units} now, then on new ones as they arrive.`
                                    : `No recent ${units} match yet, so it starts with new ones as they arrive.`
                            } Your AI provider key pays for each run.`}
                        </p>
                        <dl className="flex flex-col gap-1 m-0">
                            {estimate.units > 0 && (
                                <div className="flex justify-between gap-4">
                                    <dt className="text-secondary">{`Recent ${units} to evaluate`}</dt>
                                    <dd className="m-0">{humanFriendlyNumber(estimate.units)}</dd>
                                </div>
                            )}
                            <div className="flex justify-between gap-4">
                                <dt className="text-secondary">Model</dt>
                                <dd className="m-0 font-mono">{estimate.judge_model ?? 'Unknown'}</dd>
                            </div>
                            {estimate.units > 0 && (
                                <div className="flex justify-between gap-4">
                                    <dt className="text-secondary">Estimated cost</dt>
                                    <dd className="m-0">{costText(estimate.estimated_cost_usd)}</dd>
                                </div>
                            )}
                        </dl>
                    </>
                ) : null}
            </div>
        </LemonModal>
    )
}
