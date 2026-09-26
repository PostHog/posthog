import clsx from 'clsx'
import { toHtml } from 'hast-util-to-html'
import dart from 'highlight.js/lib/languages/dart'
import elixir from 'highlight.js/lib/languages/elixir'
import groovy from 'highlight.js/lib/languages/groovy'
import http from 'highlight.js/lib/languages/http'
import { useValues } from 'kea'
import { common, createLowlight } from 'lowlight'
import { useMemo } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import terraform from './terraformLanguage'

// `common` already registers most of our languages (including rust, c, and cpp) — only add the missing ones.
const lowlight = createLowlight(common)
lowlight.register({ dart, elixir, groovy, http, terraform })

export function HighlightedCodeLine({
    text,
    language,
    className,
}: {
    text: string
    language: string
    className?: string
}): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const highlighted = useMemo(
        () => (lowlight.registered(language) ? lowlight.highlight(language, text) : lowlight.highlightAuto(text)),
        [language, text]
    )

    return (
        <code
            className={clsx('hljs', isDarkModeOn && 'hljs-dark', className)}
            dangerouslySetInnerHTML={{ __html: toHtml(highlighted) }}
        />
    )
}
