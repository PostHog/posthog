import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceSummaryContentApi, TraceSummaryItemApi } from '../../../generated/api.schemas'
import type { SummaryItemKind } from '../types'

export interface SummaryContentProps {
    summary: TraceSummaryContentApi
    onSelectStep: (nodeId: string, kind: SummaryItemKind) => void
    actions: JSX.Element
}

interface SummaryItemListProps {
    items: TraceSummaryItemApi[]
    kind: SummaryItemKind
    onSelectStep: (nodeId: string, kind: SummaryItemKind) => void
}

function SummaryItemList({ items, kind, onSelectStep }: SummaryItemListProps): JSX.Element {
    return (
        <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5">
            {items.map(({ text, nodeId }, index) => (
                <li key={index} className="break-words">
                    <span>{text}</span>
                    {nodeId ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            className="ml-1 inline-flex align-middle"
                            sideIcon={<IconArrowRight />}
                            onClick={() => onSelectStep(nodeId, kind)}
                            data-attr="trace-view-summary-step-link"
                        >
                            View step
                        </LemonButton>
                    ) : null}
                </li>
            ))}
        </ul>
    )
}

export function SummaryContent({ summary, onSelectStep, actions }: SummaryContentProps): JSX.Element {
    const [flowShown, setFlowShown] = useState(false)
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="m-0 min-w-0 break-words text-base font-semibold">{summary.title}</h3>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-secondary">
                        Generated <TZLabel time={summary.generatedAt} />
                    </span>
                    {actions}
                </div>
            </div>
            <SummaryItemList items={summary.bullets} kind="bullet" onSelectStep={onSelectStep} />
            {summary.notes.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                    <h4 className="m-0 text-sm font-semibold">Notes</h4>
                    <SummaryItemList items={summary.notes} kind="note" onSelectStep={onSelectStep} />
                </div>
            ) : null}
            <div className="flex flex-col items-start gap-1.5">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setFlowShown(!flowShown)}
                    data-attr="trace-view-summary-flow-toggle"
                >
                    {flowShown ? 'Hide flow' : 'Show flow'}
                </LemonButton>
                {flowShown ? (
                    <pre className="m-0 max-w-full overflow-x-auto rounded border border-primary bg-surface-primary p-3 text-xs">
                        {summary.flow}
                    </pre>
                ) : null}
            </div>
        </div>
    )
}
