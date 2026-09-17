import { QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'

import { queryScanTileStatLine } from './queryScan'
import { QueryScanFindingList } from './QueryScanFindingList'

export interface QueryScanTileTooltipProps {
    summary: QueryScanSummary
    findings: QueryScanWarning[]
}

export function QueryScanTileTooltip({ summary, findings }: QueryScanTileTooltipProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span>{queryScanTileStatLine(summary)}</span>
            <QueryScanFindingList findings={findings} />
        </div>
    )
}
