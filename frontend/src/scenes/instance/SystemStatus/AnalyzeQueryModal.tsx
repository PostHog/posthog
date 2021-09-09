import React from 'react'
import { Button, Input, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'

export function AnalyzeQueryModal(): JSX.Element | null {
    const { analyzeModalOpen, analyzeQuery, analyzeQueryResult, analyzeQueryResultLoading } = useValues(
        systemStatusLogic
    )
    const { setAnalyzeModalOpen, setAnalyzeQuery, runAnalyzeQuery } = useActions(systemStatusLogic)

    return (
        <Modal
            visible={analyzeModalOpen}
            title="Analyze ClickHouse query performance"
            footer={
                <>
                    <Button onClick={() => setAnalyzeModalOpen(false)}>Cancel</Button>
                    <Button type="primary" onClick={() => void runAnalyzeQuery()} disabled={analyzeQueryResultLoading}>
                        Analyze
                    </Button>
                </>
            }
            onCancel={() => setAnalyzeModalOpen(false)}
            width="80%"
        >
            <Input.TextArea
                placeholder="SQL query to analyze"
                onChange={(e) => setAnalyzeQuery(e.target.value)}
                value={analyzeQuery}
                rows={10}
            />

            {analyzeQueryResult && (
                <div style={{ marginTop: 30 }}>
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
        </Modal>
    )
}
