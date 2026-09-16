import { Link } from 'lib/lemon-ui/Link'
import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'

// Stop the capture before trailing sentence punctuation so a URL ending a sentence (".", ")") keeps
// a clean href. No `g` flag needed: split() finds all matches and interleaves the captured URLs.
const DETAIL_URL_REGEX = /(https?:\/\/[^\s]*[^\s.,;:!?)\]}'"])/

// Render embedded URLs (e.g. backend docs links) as clickable links. Only PostHog-host URLs are
// linkified — error detail can echo user-controlled text.
export function renderDetailWithLinks(detail: string): (string | JSX.Element)[] {
    // Splitting on a capturing group interleaves text and URL matches, so odd indexes are the URLs
    return detail.split(DETAIL_URL_REGEX).map((part, index) =>
        index % 2 === 1 && isTrustedPostHogUrl(part) ? (
            <Link key={index} to={part} target="_blank">
                {part}
            </Link>
        ) : (
            part
        )
    )
}
