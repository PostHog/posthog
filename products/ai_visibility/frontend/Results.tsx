interface ResultsProps {
    results: Record<string, unknown>
    domain: string
    runId: string | null
}

export function Results({ results, domain, runId }: ResultsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <h3 className="text-base font-semibold">Results for {domain}</h3>
                {runId && <p className="text-xs text-muted font-mono">Run ID: {runId}</p>}
            </div>

            <div className="rounded border border-border bg-bg-300 p-4">
                {results.summary && (
                    <div className="mb-4">
                        <h4 className="text-sm font-medium mb-1">Summary</h4>
                        <p className="text-sm">{String(results.summary)}</p>
                    </div>
                )}

                {results.topics && Array.isArray(results.topics) && (
                    <div className="mb-4">
                        <h4 className="text-sm font-medium mb-1">Topics</h4>
                        <ul className="list-disc list-inside text-sm">
                            {results.topics.map((topic, idx) => (
                                <li key={idx}>{String(topic)}</li>
                            ))}
                        </ul>
                    </div>
                )}

                {results.ai_calls && Array.isArray(results.ai_calls) && (
                    <div className="mb-4">
                        <h4 className="text-sm font-medium mb-2">AI Calls</h4>
                        <div className="flex flex-col gap-2">
                            {results.ai_calls.map((call, idx) => (
                                <div key={idx} className="rounded border border-border-light bg-bg-200 p-2 text-sm">
                                    <div className="font-medium">
                                        {String((call as Record<string, unknown>).prompt)}
                                    </div>
                                    <div className="text-muted">{String((call as Record<string, unknown>).result)}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                <details className="mt-4">
                    <summary className="cursor-pointer text-sm text-muted">Raw JSON</summary>
                    <pre className="mt-2 text-xs bg-bg-100 p-2 rounded overflow-auto max-h-64">
                        {JSON.stringify(results, null, 2)}
                    </pre>
                </details>
            </div>
        </div>
    )
}
