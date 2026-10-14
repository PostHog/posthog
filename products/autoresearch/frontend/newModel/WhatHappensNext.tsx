const STEPS = [
    'An agent builds features from your events and trains candidate models on past data.',
    'It keeps the model with the best holdout score, and stops when the score stops improving or the experiment budget runs out.',
    'The best model scores your population every day and saves each score as a person property.',
    'When the prediction horizon passes, Autoresearch compares the predictions with what people did.',
]

export function WhatHappensNext(): JSX.Element {
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
        </div>
    )
}
