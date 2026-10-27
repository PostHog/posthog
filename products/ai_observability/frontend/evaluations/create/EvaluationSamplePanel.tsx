import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconRefresh } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { useAIData } from '../../hooks/useAIData'
import { normalizeMessage } from '../../messageNormalization'
import { extractText, selectAiValue } from '../../utils'
import { type SampleGeneration, evaluationSampleLogic } from '../evaluationSampleLogic'
import { VOLUME_LOOKBACK_DAYS, filtersOnContent } from '../evaluationVolume'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

const HogSearching = pngHoggie(magnifyingGlassPng)

/** The last message with text in a role, from a raw `$ai_input` or `$ai_output_choices` value. */
function lastText(raw: unknown, role: string): string {
    const messages = raw == null ? [] : normalizeMessage(raw, role)
    for (let index = messages.length - 1; index >= 0; index--) {
        const text = messages[index].role === role ? extractText(messages[index]).trim() : ''
        if (text) {
            return text
        }
    }
    return ''
}

function SampleMessages({ sample }: { sample: SampleGeneration }): JSX.Element {
    const { input, output, isLoading } = useAIData({
        uuid: sample.id,
        input: sample.properties.$ai_input,
        output: selectAiValue(sample.properties.$ai_output_choices, sample.properties.$ai_output),
        traceId: sample.properties.$ai_trace_id,
        timestamp: sample.timestamp,
    })
    if (isLoading) {
        return <Spinner />
    }
    const rows: [string, string][] = [
        ['User', lastText(input, 'user')],
        ['Response', lastText(output, 'assistant')],
    ]
    return (
        <dl className="m-0 flex flex-col gap-2 text-sm">
            {rows.map(([label, text]) => (
                <div key={label} className="flex flex-col gap-0.5">
                    <dt className="text-xs font-semibold text-secondary">{label}</dt>
                    <dd className="m-0 line-clamp-6 whitespace-pre-wrap break-words">
                        {text || <span className="text-secondary">No text captured</span>}
                    </dd>
                </div>
            ))}
        </dl>
    )
}

/** A recent generation the triggers match, so the instructions can be checked against real traffic. */
export function EvaluationSamplePanel(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { sample, samples, samplesLoading, samplesError } = useValues(evaluationSampleLogic)
    const { showNextSample } = useActions(evaluationSampleLogic)

    if (!evaluation) {
        return null
    }

    let body: JSX.Element
    if (filtersOnContent(evaluation.conditions)) {
        body = <p className="mb-0 text-sm text-secondary">No example, because a filter checks the input or output.</p>
    } else if (samplesError) {
        body = <p className="mb-0 text-sm text-secondary">Couldn't load an example. Change a filter to try again.</p>
    } else if (!sample) {
        body = samplesLoading ? (
            <Spinner />
        ) : (
            <div className="flex flex-col items-center gap-2 py-2 text-center">
                <HogSearching className="w-16" />
                <p className="mb-0 text-sm text-secondary">
                    {`No generation matched in the last ${VOLUME_LOOKBACK_DAYS} days.`}
                </p>
            </div>
        )
    } else {
        body = <SampleMessages key={sample.id} sample={sample} />
    }

    return (
        <section
            className="bg-bg-light border rounded p-4 flex flex-col gap-3"
            data-attr="llma-evaluation-create-sample"
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col min-w-0">
                    <h3 className="mb-0 text-base font-semibold">Example</h3>
                    <span className="text-xs text-secondary">A recent generation your triggers match.</span>
                </div>
                {(samples?.length ?? 0) > 1 && (
                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        tooltip="Show another one"
                        onClick={showNextSample}
                        data-attr="llma-evaluation-create-sample-next"
                    />
                )}
            </div>
            {body}
        </section>
    )
}
