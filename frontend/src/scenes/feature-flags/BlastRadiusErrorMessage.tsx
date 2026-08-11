import { Link } from '@posthog/lemon-ui'

import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'

import { BlastRadiusError, blastRadiusErrorMessage } from './featureFlagReleaseConditionsLogic'

// Splitting on a capturing group interleaves text and URL matches, so odd indexes are the URLs.
const DETAIL_URL_REGEX = /(https?:\/\/[^\s]*[^\s.,;:!?)\]}'"])/

// Renders a failed blast-radius estimate's message, turning a trusted PostHog URL in the backend's
// copy (e.g. the docs link a memory-limit error carries) into a link. Only PostHog-host URLs are
// linkified, since the detail can echo user-controlled filter text.
export function BlastRadiusErrorMessage({
    error,
    pluralName,
}: {
    error: BlastRadiusError
    pluralName: string
}): JSX.Element {
    const message = blastRadiusErrorMessage(error, pluralName)
    return (
        <span>
            {message.split(DETAIL_URL_REGEX).map((part, index) =>
                index % 2 === 1 && isTrustedPostHogUrl(part) ? (
                    <Link key={index} to={part} target="_blank">
                        {part}
                    </Link>
                ) : (
                    part
                )
            )}
        </span>
    )
}
