import { renderDetailWithLinks } from 'lib/utils/renderDetailWithLinks'

import { BlastRadiusError, getBlastRadiusErrorMessage } from './featureFlagReleaseConditionsLogic'

export function BlastRadiusErrorMessage({
    error,
    pluralName,
}: {
    error: BlastRadiusError
    pluralName: string
}): JSX.Element {
    return (
        <span className="min-w-0 break-words">
            {renderDetailWithLinks(getBlastRadiusErrorMessage(error, pluralName))}
        </span>
    )
}
