import { Link } from 'lib/lemon-ui/Link'
import { DETAIL_URL_REGEX } from 'lib/utils/renderDetailWithLinks'

// Exception messages often point at the docs for the error, such as React's minified error page,
// so every http(s) URL becomes a link. Each part gets its own element because a page-translation
// extension can replace a bare text node next to a sibling, and React then crashes on update.
export function ExceptionMessage({ value }: { value: string }): JSX.Element {
    return (
        <>
            {value.split(DETAIL_URL_REGEX).map((part, index) =>
                index % 2 === 1 ? (
                    <Link
                        key={index}
                        to={part}
                        target="_blank"
                        targetBlankIcon={false}
                        // The message sits in a selectable row or an expand toggle, which must not also react
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                    >
                        {part}
                    </Link>
                ) : part ? (
                    <span key={index}>{part}</span>
                ) : null
            )}
        </>
    )
}
