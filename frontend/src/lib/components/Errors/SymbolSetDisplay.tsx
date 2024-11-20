import { LemonCollapse, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { symbolSetLogic } from './symbolSetLogic'
import { ErrorTrackingStackFrameRecord, ErrorTrackingSymbolSet } from './types'

function StackFrameDisplay({ frame }: { frame: ErrorTrackingStackFrameRecord }): JSX.Element {
    const { contents } = frame

    return (
        <LemonCollapse
            panels={[
                {
                    key: frame.raw_id,
                    header: (
                        <div className="flex flex-wrap space-x-0.5">
                            <span>{contents.source || 'Unknown source'}</span>
                            {contents.resolved_name && (
                                <div className="flex space-x-0.5">
                                    <span className="text-muted">in</span>
                                    <span>{contents.resolved_name}</span>
                                </div>
                            )}
                            {contents.line && (
                                <div className="flex space-x-0.5">
                                    <span className="text-muted">at line</span>
                                    <span>
                                        {contents.line}:{contents.column || 0}
                                    </span>
                                </div>
                            )}
                        </div>
                    ),
                    content: frame.context && <div className="font-mono text-xs whitespace-pre">{frame.context}</div>, // TODO - this needs to account for structure context later
                },
            ]}
        />
    )
}

function SymbolSetDisplay({ symbolSet }: { symbolSet: ErrorTrackingSymbolSet }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const { symbolSetStackFrames, symbolSetStackFramesLoading } = useValues(symbolSetLogic)
    const { loadStackFrames } = useActions(symbolSetLogic)

    useEffect(() => {
        if (expanded && !symbolSetStackFrames[symbolSet.id]) {
            loadStackFrames({ symbolSetId: symbolSet.id })
        }
    }, [expanded, symbolSet.id, loadStackFrames, symbolSetStackFrames])

    return (
        <LemonCollapse
            panels={[
                {
                    key: symbolSet.id,
                    header: (
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <h3 className="mb-0">{symbolSet.ref}</h3>
                                {symbolSet.failure_reason && (
                                    <div className="text-danger">Failed: {symbolSet.failure_reason}</div>
                                )}
                            </div>
                            <div className="text-muted">Storage: {symbolSet.storage_ptr || 'Not stored'}</div>
                        </div>
                    ),
                    content: (
                        <div className="flex flex-col gap-4 mt-4">
                            {symbolSetStackFramesLoading ? (
                                <div className="flex justify-center">
                                    <Spinner className="text-xl" />
                                </div>
                            ) : (
                                symbolSetStackFrames[symbolSet.id]?.map((frame: ErrorTrackingStackFrameRecord) => (
                                    <StackFrameDisplay key={frame.raw_id} frame={frame} />
                                ))
                            )}
                        </div>
                    ),
                },
            ]}
            onChange={(key) => setExpanded(!!key)}
        />
    )
}

export function SymbolSetsDisplay(): JSX.Element {
    const { symbolSets, symbolSetsLoading } = useValues(symbolSetLogic)
    const { loadSymbolSets } = useActions(symbolSetLogic)

    useEffect(() => {
        loadSymbolSets()
    }, [loadSymbolSets])

    if (symbolSetsLoading) {
        return (
            <div className="flex justify-center">
                <Spinner className="text-xl" />
            </div>
        )
    }

    if (!symbolSets?.length) {
        return <div className="text-muted">No symbol sets found</div>
    }

    return (
        <div className="flex flex-col space-y-4">
            {symbolSets.map((symbolSet) => (
                <SymbolSetDisplay key={symbolSet.id} symbolSet={symbolSet} />
            ))}
        </div>
    )
}
