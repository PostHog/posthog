import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconRefresh } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { ConversationDisplay } from '../../ConversationDisplay/ConversationDisplay'
import { evaluationSampleLogic } from '../evaluationSampleLogic'
import { VOLUME_LOOKBACK_DAYS, filtersOnContent } from '../evaluationVolume'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

const HogSearching = pngHoggie(magnifyingGlassPng)

/** A recent generation the triggers match, so the instructions get written against what the evaluation will read. */
export function EvaluationSamplePanel(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { sample, samples, samplesLoading, samplesError } = useValues(evaluationSampleLogic)
    const { showNextSample } = useActions(evaluationSampleLogic)

    if (!evaluation) {
        return null
    }
    const reader =
        evaluation.evaluation_type === 'llm_judge'
            ? 'the judge'
            : evaluation.evaluation_type === 'hog'
              ? 'your code'
              : 'the classifier'

    let body: JSX.Element
    if (filtersOnContent(evaluation.conditions)) {
        body = (
            <p className="mb-0 text-sm text-secondary">
                Couldn't load an example, because a filter checks the input or output.
            </p>
        )
    } else if (samplesError) {
        body = <p className="mb-0 text-sm text-secondary">Couldn't load an example. Change a filter to try again.</p>
    } else if (!sample) {
        body = samplesLoading ? (
            <p className="mb-0 flex items-center gap-2 text-sm text-secondary">
                <Spinner />
                Finding a recent generation
            </p>
        ) : (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
                <HogSearching className="w-24" />
                <p className="mb-0 text-sm text-secondary">
                    {`No generation matched in the last ${VOLUME_LOOKBACK_DAYS} days. Examples show here once one does.`}
                </p>
            </div>
        )
    } else {
        body = (
            // The shared header puts its stats and the playground button in one row, too wide for this column.
            <div className="max-h-[36rem] overflow-y-auto [&_header]:flex-wrap [&_header]:gap-2">
                <ConversationDisplay
                    key={sample.id}
                    eventId={sample.id}
                    eventName="$ai_generation"
                    eventProperties={sample.properties}
                    eventTimestamp={sample.timestamp}
                />
            </div>
        )
    }

    return (
        <section className="flex flex-col gap-2 min-w-0" data-attr="llma-evaluation-create-sample">
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-0.5 min-w-0">
                    <h4 className="mb-0 text-base font-semibold">What {reader} reads</h4>
                    <span className="text-xs text-secondary">
                        {evaluation.target === 'generation' || evaluation.evaluation_type === 'sentiment'
                            ? 'A recent generation that matches the triggers.'
                            : `One generation from a matching ${evaluation.target}. The run reads the whole ${evaluation.target}.`}
                    </span>
                </div>
                {(samples?.length ?? 0) > 1 && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={showNextSample}
                        data-attr="llma-evaluation-create-sample-next"
                    >
                        Another one
                    </LemonButton>
                )}
            </div>
            <div className="border rounded p-3 bg-surface-primary min-w-0">{body}</div>
        </section>
    )
}
