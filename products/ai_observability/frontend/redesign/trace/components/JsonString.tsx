import { useId, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

export function JsonString({
    value,
    collapseStringsAfterLength,
}: {
    value: string
    collapseStringsAfterLength?: number
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const textId = useId()
    const canCollapse = !!collapseStringsAfterLength && value.length > collapseStringsAfterLength

    return (
        <>
            <p id={textId} className="m-0 whitespace-pre-wrap break-words text-sm">
                {canCollapse && !expanded ? `${value.slice(0, collapseStringsAfterLength)}…` : value}
            </p>
            {canCollapse && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="mt-1"
                    onClick={() => setExpanded((open) => !open)}
                    aria-controls={textId}
                    aria-expanded={expanded}
                    data-attr="ai-observability-json-string-toggle"
                >
                    {expanded ? 'Show less' : 'Show more'}
                </LemonButton>
            )}
        </>
    )
}
