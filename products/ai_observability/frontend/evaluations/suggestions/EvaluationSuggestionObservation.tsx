export function EvaluationSuggestionObservation({
    observation,
    scope,
}: {
    observation: string
    scope: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 p-2 rounded bg-surface-secondary border-l-2 border-warning">
            <span className="text-sm font-semibold">{observation}</span>
            {scope && <span className="text-xs text-secondary">{scope}</span>}
        </div>
    )
}
