import { LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export interface SourceReleaseTagProps {
    releaseStatus?: SourceConfigResponseApi['releaseStatus']
}

export function SourceReleaseTag({ releaseStatus }: SourceReleaseTagProps): JSX.Element | null {
    if (releaseStatus === 'beta') {
        return (
            <Tooltip title="Beta means this is a new source that is still being validated with real syncs">
                <LemonTag type="completion">Beta</LemonTag>
            </Tooltip>
        )
    }
    return null
}
