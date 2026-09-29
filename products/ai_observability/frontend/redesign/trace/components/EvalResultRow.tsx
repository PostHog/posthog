import { EvalResult } from '../types'
import { EvalVerdictTag } from './EvalVerdictTag'

export interface EvalResultRowProps {
    result: EvalResult
}

export function EvalResultRow({ result }: EvalResultRowProps): JSX.Element {
    return (
        <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 py-2">
            <span className="font-semibold text-sm">{result.name}</span>
            <EvalVerdictTag verdict={result.verdict} />
            {result.reasoning ? <span className="text-secondary text-xs">{result.reasoning}</span> : null}
        </li>
    )
}
