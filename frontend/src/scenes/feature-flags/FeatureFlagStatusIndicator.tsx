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
        [
            FeatureFlagStatus.ACTIVE,
            FeatureFlagStatus.INACTIVE,
            FeatureFlagStatus.DELETED,
            FeatureFlagStatus.UNKNOWN,
        ].includes(flagStatus.status)
    ) {
        return null
    }

    return (
        <Tooltip
            title={
                <>
                    <div className="text-sm">{flagStatus.reason}</div>
                    <div className="text-xs">
                        {flagStatus.status === FeatureFlagStatus.STALE &&
                            'Make sure to remove any references to this flag in your code before deleting it.'}
                        {flagStatus.status === FeatureFlagStatus.INACTIVE &&
                            'It is probably not being used in your code, but be sure to remove any references to this flag before deleting it.'}
                    </div>
                </>
            }
            placement="right"
        >
            <span>
                <LemonTag type="warning" className="uppercase cursor-default">
                    {flagStatus.status}
                </LemonTag>
            </span>
        </Tooltip>
    )
}
