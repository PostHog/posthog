import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { UnprunedTableScan } from '~/queries/schema/schema-general'

interface UnprunedScanNoticeProps {
    scans: UnprunedTableScan[]
}

export function UnprunedScanNotice({ scans }: UnprunedScanNoticeProps): JSX.Element | null {
    if (scans.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 px-2 py-2">
            {scans.map((scan, index) => (
                <div key={`${scan.table_name}-${scan.start ?? index}`} className="flex items-start gap-2 text-xs">
                    <LemonTag type="warning">No time range</LemonTag>
                    <div className="flex flex-col gap-0.5">
                        <span>{scan.message}</span>
                        <span className="font-semibold">{scan.fix}</span>
                        <span className="text-secondary">
                            <code>{scan.table_name}</code> is partitioned by <code>{scan.partition_key}</code>, so a
                            filter on the partition key is what limits how much is read.
                        </span>
                    </div>
                </div>
            ))}
        </div>
    )
}
