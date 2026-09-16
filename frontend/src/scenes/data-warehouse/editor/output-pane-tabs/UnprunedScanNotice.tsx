import { LemonButton } from '@posthog/lemon-ui'

import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { HogQLFixEdit, UnprunedTableScan } from '~/queries/schema/schema-general'

interface UnprunedScanNoticeProps {
    scans: UnprunedTableScan[]
    /** Absent while the report is stale, so the offsets in a fix no longer match the editor text. */
    onApplyFix?: (edits: HogQLFixEdit[]) => void
}

export function UnprunedScanNotice({ scans, onApplyFix }: UnprunedScanNoticeProps): JSX.Element | null {
    if (scans.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 px-2 py-2">
            {scans.map((scan, index) => (
                <div key={`${scan.table_name}-${scan.start ?? index}`} className="flex items-start gap-2 text-xs">
                    <LemonTag type="warning">No time range</LemonTag>
                    <div className="flex flex-col items-start gap-1">
                        <span>{scan.message}</span>
                        <span className="font-semibold">{scan.fix}</span>
                        <span className="text-secondary">
                            <code>{scan.table_name}</code> is partitioned by <code>{scan.partition_key}</code>, so a
                            filter on the partition key is what limits how much is read.
                        </span>
                        {scan.fix_action && onApplyFix && (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                data-attr="sql-editor-apply-time-range-fix"
                                onClick={() => onApplyFix(scan.fix_action!.edits)}
                            >
                                {scan.fix_action.title}
                            </LemonButton>
                        )}
                    </div>
                </div>
            ))}
        </div>
    )
}
