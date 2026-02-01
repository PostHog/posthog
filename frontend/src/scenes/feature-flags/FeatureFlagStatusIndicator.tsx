import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { FeatureFlagStatus, FeatureFlagStatusResponse } from '~/types'

export function FeatureFlagStatusIndicator({
    flagStatus,
}: {
    flagStatus: FeatureFlagStatusResponse | null
}): JSX.Element | null {
    if (
        !flagStatus ||
        [FeatureFlagStatus.ACTIVE, FeatureFlagStatus.DELETED, FeatureFlagStatus.UNKNOWN].includes(flagStatus.status)
    ) {
        return null
    }

    const tagType = flagStatus.status === FeatureFlagStatus.INACTIVE ? 'danger' : 'warning'

    return (
        <Tooltip
            title={
                <>
                    <div className="text-sm">{flagStatus.reason}</div>
                    <div className="text-xs">
                        {flagStatus.status === FeatureFlagStatus.STALE &&
                            'Make sure to remove any references to this flag in your code before deleting it.'}
                        {flagStatus.status === FeatureFlagStatus.INACTIVE &&
                            'This flag appears unused. Verify it is not needed before removing it.'}
                    </div>
                </>
            }
            placement="right"
        >
            <span>
                <LemonTag type={tagType} className="uppercase cursor-default">
                    {flagStatus.status}
                </LemonTag>
            </span>
        </Tooltip>
    )
}
