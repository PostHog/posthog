import React from 'react'

export const URL_MATCHING_HINTS: Record<string, JSX.Element | null> = {
    exact: null,
    contains: (
        <>
            Use <code>%</code> for wildcard, for example: <code>/user/%/edit</code>.
        </>
    ),
    regex: (
        <>
            <a
                href="https://www.postgresql.org/docs/current/functions-matching.html#FUNCTIONS-POSIX-REGEXP"
                target="_blank"
                rel="noreferrer"
            >
                PostgreSQL regular expression syntax
            </a>{' '}
            applies.
        </>
    ),
}
