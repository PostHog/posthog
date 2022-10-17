import { useActions, useValues } from 'kea'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

export function AnalyzeQueryModal(): JSX.Element | null {
    const { analyzeModalOpen, analyzeQuery, analyzeQueryResult, analyzeQueryResultLoading } =
        useValues(systemStatusLogic)
    const { setAnalyzeModalOpen, setAnalyzeQuery, runAnalyzeQuery } = useActions(systemStatusLogic)

    return (
        <LemonModal
            isOpen={analyzeModalOpen}
            title="Analyze ClickHouse query performance"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setAnalyzeModalOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => void runAnalyzeQuery()}
                        disabled={analyzeQueryResultLoading}
                    >
                        Analyze
                    </LemonButton>
                </>
            }
            onClose={() => setAnalyzeModalOpen(false)}
            width="80%"
        >
            <LemonTextArea
                placeholder="SQL query to analyze"
                onChange={setAnalyzeQuery}
                value={analyzeQuery}
                rows={10}
            />

            {analyzeQueryResult && (
                <div className="mt-2">
                    <h2>Analysis results</h2>

                    <ul>
                        {Object.entries(analyzeQueryResult.timing).map(([key, value]) => (
                            <li key={key}>
                                {key}: {value}
                            </li>
                        ))}
                    </ul>

                    {Object.entries(analyzeQueryResult.flamegraphs).map(([key, value]) => (
                        <div key={key}>
                            <h3>Flamegraph: {key}</h3>

                            <a
                                className="embedded-svg-wrapper"
                                href={`data:image/svg+xml;utf8,${encodeURIComponent(value)}`}
                                dangerouslySetInnerHTML={{ __html: value }}
                            />
                        </div>
                    ))}
                </div>
            )}
        </LemonModal>
    )
}
