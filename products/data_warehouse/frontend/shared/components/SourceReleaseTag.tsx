import { LabsTag } from 'lib/lemon-ui/LabsTag'

import { SourceConfig } from '~/queries/schema/schema-general'

export interface SourceReleaseTagProps {
    releaseStatus?: SourceConfig['releaseStatus']
}

export function SourceReleaseTag({ releaseStatus }: SourceReleaseTagProps): JSX.Element | null {
    if (releaseStatus === 'alpha' || releaseStatus === 'beta') {
        return <LabsTag stage={releaseStatus} />
    }
    return null
}
