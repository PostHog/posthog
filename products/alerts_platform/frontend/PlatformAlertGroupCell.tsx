import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PlatformAlertApi } from './generated/api.schemas'
import { groupLabels } from './platformAlertFormat'

export function PlatformAlertGroupCell({
    alert,
    groupingKeys,
}: {
    alert: PlatformAlertApi
    groupingKeys: readonly string[]
}): JSX.Element {
    if (!alert.grouping_key) {
        return <span className="text-secondary">Ungrouped</span>
    }
    const labels = groupLabels(alert, groupingKeys)
    if (!labels.length) {
        return <span className="break-all">{alert.grouping_key}</span>
    }
    return (
        <Tooltip title={`Group key: ${alert.grouping_key}`}>
            {/* An auto-layout table sizes a column to its widest unbreakable content, so a long label
                pushes the snooze action off screen. A container-relative cap lets the tag truncate. */}
            <div className="flex flex-wrap gap-1 max-w-[35cqw]" translate="no">
                {labels.map(({ key, name, value }) => (
                    <LemonTag key={key} type="muted" className="max-w-full">
                        <span className="truncate">
                            {name}: {value}
                        </span>
                    </LemonTag>
                ))}
            </div>
        </Tooltip>
    )
}
