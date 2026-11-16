import { Link } from 'lib/lemon-ui/Link'
import { DETAIL_URL_REGEX } from 'lib/utils/renderDetailWithLinks'

const BIDI_CONTROLS = /[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/

function isLinkableUrl(value: string): boolean {
    if (BIDI_CONTROLS.test(value)) {
        return false
    }
    try {
        const url = new URL(value)
        return (
            (url.protocol === 'https:' || url.protocol === 'http:') &&
            !url.username &&
            !url.password &&
            value.startsWith(`${url.protocol}//${url.host}`)
        )
    } catch {
        return false
    }
}

// Separate elements prevent page-translation extensions from detaching text nodes React still needs.
export function ExceptionMessage({ value }: { value: string }): JSX.Element {
    return (
        <>
            {value.split(DETAIL_URL_REGEX).map((part, index) =>
                index % 2 === 1 && isLinkableUrl(part) ? (
                    <bdi key={index} dir="ltr">
                        <Link
                            to={part}
                            target="_blank"
                            title={part}
                            targetBlankIcon={false}
                            // The message sits in a selectable row or an expand toggle, which must not also react
                            onClick={(e) => e.stopPropagation()}
                            onKeyDown={(e) => e.stopPropagation()}
                        >
                            {part}
                        </Link>
                    </bdi>
                ) : part ? (
                    <span key={index}>{part}</span>
                ) : null
            )}
        </>
    )
}
