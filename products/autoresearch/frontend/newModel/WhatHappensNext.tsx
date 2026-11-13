import { useValues } from 'kea'

import { autoresearchNewLogic } from '../autoresearchNewLogic'

const STEPS = [
    'An agent builds features from your events and trains candidate models on past data.',
    'It keeps the model with the best holdout score, and stops when the score stops improving or the experiment budget runs out.',
    'The best model scores your population every day and saves each score as a person property.',
    'When the prediction horizon passes, Autoresearch compares the predictions with what people did.',
]

export function WhatHappensNext(): JSX.Element {
    const { projectLimitsSummary } = useValues(autoresearchNewLogic)
    return (
        <div className="border rounded p-4 flex flex-col gap-3">
            <h3 className="text-base font-semibold mb-0">What happens next</h3>
            <ol className="flex flex-col gap-2 text-sm list-none p-0 m-0">
                {STEPS.map((step, index) => (
                    <li key={index} className="flex gap-2">
                        <span className="flex items-center justify-center shrink-0 size-5 rounded-full bg-fill-highlight-100 text-xs font-semibold">
                            {index + 1}
                        </span>
                        <span>{step}</span>
                    </li>
                ))}
            </ol>
            <div className="flex flex-col gap-1 text-xs text-secondary">
                <span>
                    A training run usually takes 30 to 60 minutes. The first scores arrive with the next daily scoring
                    run after it.
                </span>
                {projectLimitsSummary && (
                    <span data-attr="autoresearch-new-project-limits">{projectLimitsSummary}</span>
                )}
            </div>
        </div>
    )
}
