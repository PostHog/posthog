import { useState } from 'react'

import { Button } from '@posthog/quill'

import { JSONViewer } from 'lib/components/JSONViewer'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { TZLabel } from 'lib/components/TZLabel'

import { WARNING_TYPE_RENDERER } from '../ingestion-warnings/ingestionWarningTypes'
import { IngestionWarningV2Sample, IngestionWarningV2Summary } from './ingestionWarningsV2Logic'
import { QuillSampleEntityChips } from './QuillSampleEntityChips'

// In production this list can be long, so it is paged rather than rendered at once.
const PAGE_SIZE = 20

const sampleKey = (sample: IngestionWarningV2Sample): string => `${sample.timestamp}-${sample.event_uuid ?? ''}`

function QuillWarningSample({ type, sample }: { type: string; sample: IngestionWarningV2Sample }): JSX.Element {
    const [showDetails, setShowDetails] = useState(false)
    const renderer = WARNING_TYPE_RENDERER[type as keyof typeof WARNING_TYPE_RENDERER]

    return (
        <li className="flex gap-3 border-b border-border py-2 last:border-b-0">
            <div className="flex w-40 shrink-0 flex-col gap-0.5 font-mono text-xs">
                <TZLabel time={sample.timestamp} showSeconds />
                {sample.pipeline_step !== 'unknown' && (
                    <span className="text-muted-foreground [overflow-wrap:anywhere]">{sample.pipeline_step}</span>
                )}
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1 [overflow-wrap:anywhere]">
                <QuillSampleEntityChips sample={sample} />
                {renderer ? (
                    <div className="text-xs [&_ul]:list-disc [&_ul]:pl-5">
                        {renderer({ type, timestamp: sample.timestamp, details: sample.details })}
                    </div>
                ) : (
                    <span className="font-mono text-xs break-all text-muted-foreground">
                        {JSON.stringify(sample.details)}
                    </span>
                )}
                <Button
                    variant="link-muted"
                    size="inline"
                    className="self-start"
                    aria-expanded={showDetails}
                    onClick={() => setShowDetails(!showDetails)}
                >
                    {showDetails ? 'Hide details' : 'Show details'}
                </Button>
                {showDetails && (
                    <div className="font-mono text-xs">
                        <JSONViewer src={sample.details} name="details" collapsed={false} />
                    </div>
                )}
            </div>
        </li>
    )
}

/** The samples of one warning type, listed inside its expanded row. */
export function QuillWarningSamples({ summary }: { summary: IngestionWarningV2Summary }): JSX.Element {
    const [page, setPage] = useState(1)
    const pageCount = Math.max(1, Math.ceil(summary.samples.length / PAGE_SIZE))
    const pageSamples = summary.samples.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

    return (
        // A click inside the samples must not collapse the warning row they sit in. `w-0 min-w-full` lets the
        // samples fill the warning column without widening it, which would push the other columns out of view.
        <div data-row-click-ignore className="mt-2 flex w-0 min-w-full cursor-auto flex-col gap-2 whitespace-normal">
            <ul className="flex flex-col">
                {pageSamples.map((sample) => (
                    <QuillWarningSample key={sampleKey(sample)} type={summary.type} sample={sample} />
                ))}
            </ul>
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={page}
                    pageCount={pageCount}
                    pageSize={PAGE_SIZE}
                    total={summary.samples.length}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
