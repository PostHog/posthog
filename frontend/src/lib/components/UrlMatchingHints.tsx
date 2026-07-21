import { Link } from '@posthog/lemon-ui'

export const URL_MATCHING_HINTS = {
    exact: undefined,
    contains: (
        <>
            Use <code>%</code> for wildcard, for example: <code>/user/%/edit</code>.
        </>
    ),
    regex: (
        <Link to="https://github.com/google/re2/wiki/Syntax" target="_blank">
            RE2 syntax applies.
        </Link>
    ),
}
