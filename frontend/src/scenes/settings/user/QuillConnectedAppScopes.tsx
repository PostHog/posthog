import { useState } from 'react'

import { Badge, Button } from '@posthog/quill'

import { sortScopesWriteFirst } from './connectedAppScopes'

const VISIBLE_SCOPES = 3

export function QuillConnectedAppScopes({ scopes }: { scopes: string[] }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    const sorted = sortScopesWriteFirst(scopes)
    const needsAccordion = sorted.length > VISIBLE_SCOPES
    const visible = expanded || !needsAccordion ? sorted : sorted.slice(0, VISIBLE_SCOPES)

    return (
        <div className="flex flex-wrap items-center gap-1">
            {visible.map((scope) => (
                <Badge key={scope} variant={scope.endsWith(':write') ? 'warning' : 'default'}>
                    {scope}
                </Badge>
            ))}
            {needsAccordion && (
                <Button size="xs" variant="outline" onClick={() => setExpanded(!expanded)}>
                    {expanded ? 'Show less' : `+${sorted.length - VISIBLE_SCOPES} more`}
                </Button>
            )}
        </div>
    )
}
