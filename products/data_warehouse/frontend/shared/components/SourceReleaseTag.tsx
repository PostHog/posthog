import { PreviewTag } from 'lib/lemon-ui/PreviewTag'

import { SourceConfig } from '~/queries/schema/schema-general'

export interface SourceReleaseTagProps {
    releaseStatus?: SourceConfig['releaseStatus']
}

export function SourceReleaseTag({ releaseStatus }: SourceReleaseTagProps): JSX.Element | null {
    if (releaseStatus === 'alpha' || releaseStatus === 'beta') {
        return <PreviewTag stage={releaseStatus} />
    }
    return null
}
