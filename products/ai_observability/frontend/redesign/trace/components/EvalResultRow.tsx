import { LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { EvalResult } from '../types'
import { EvalOutcomeTag } from './EvalOutcomeTag'

export interface EvalResultRowProps {
    result: EvalResult
    onSelectNode: (nodeId: string) => void
}

export function EvalResultRow({ result, onSelectNode }: EvalResultRowProps): JSX.Element {
    const { target } = result
    return (
        <li className="flex flex-col gap-1 px-3 py-2">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                {result.href ? (
                    <Link
                        to={result.href}
                        className="font-semibold text-sm"
                        data-attr="trace-view-eval-link"
                        targetBlankIcon={false}
                    >
                        {result.name}
                    </Link>
                ) : (
                    <span className="font-semibold text-sm">{result.name}</span>
                )}
                <EvalOutcomeTag outcome={result.outcome} label={result.label} />
                {result.isBackfill ? (
                    <LemonTag type="muted" size="small" title="A backfill over past data produced this result.">
                        Backfill
                    </LemonTag>
                ) : null}
                <span className="ml-auto flex items-center gap-2 text-xs text-secondary">
                    {target ? (
                        <Link
                            onClick={() => onSelectNode(target.nodeId)}
                            className="max-w-60 truncate font-mono"
                            title={`Show ${target.label}`}
                            data-attr="trace-view-eval-target"
                        >
                            {target.label}
                        </Link>
                    ) : null}
                    <TZLabel time={result.timestamp} timestampStyle="absolute" formatDate="MMM D," formatTime="HH:mm" />
                </span>
            </div>
            {result.reasoning ? <p className="m-0 text-secondary text-xs">{result.reasoning}</p> : null}
        </li>
    )
}
