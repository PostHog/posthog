import { LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export interface SourceReleaseTagProps {
    releaseStatus?: SourceConfigResponseApi['releaseStatus']
}

export function SourceReleaseTag({ releaseStatus }: SourceReleaseTagProps): JSX.Element | null {
    if (releaseStatus === 'alpha') {
        return (
            <Tooltip title="Alpha means this is a new source and hasn't been extensively tested yet">
                <LemonTag type="danger">Alpha</LemonTag>
            </Tooltip>
        )
    }
    if (releaseStatus === 'beta') {
        return (
            <Tooltip title="Beta means this source has been tested and most rough edges have been ironed out — getting ready for general availability">
                <LemonTag type="completion">Beta</LemonTag>
            </Tooltip>
        )
    }
    return null
}
