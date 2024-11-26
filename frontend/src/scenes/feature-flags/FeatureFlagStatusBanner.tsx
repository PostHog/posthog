import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { FeatureFlagStatus, FeatureFlagStatusResponse } from '~/types'

export function FeatureFlagStatusBanner({
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

    return (
        <LemonBanner type="warning">
            <div>
                <span className="font-bold">This feature flag is {flagStatus.status.toLowerCase()}</span>
                {flagStatus.reason ? ` - ${flagStatus.reason}.` : ''}
            </div>
            <div className="text-xs">
                {flagStatus.status === FeatureFlagStatus.STALE &&
                    ' Make sure to remove any references to this flag in your code before deleting it.'}
                {flagStatus.status === FeatureFlagStatus.INACTIVE &&
                    ' It is probably not being used in your code, but be sure to remove any references to this flag before deleting it.'}
            </div>
        </LemonBanner>
    )
}
