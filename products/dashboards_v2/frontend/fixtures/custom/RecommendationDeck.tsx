import { useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import {
    Button,
    Callout,
    CalloutActions,
    CalloutClose,
    CalloutContent,
    CalloutDescription,
    CalloutTitle,
    Text,
} from '@posthog/quill'

const RECOMMENDATIONS = [
    { title: 'Upload source maps', body: 'Stack traces show minified code until source maps are uploaded.' },
    { title: 'Turn on alerts', body: 'Get told when a new issue appears or an old one comes back.' },
    { title: 'Summarize issues', body: 'Get a short summary of what each new issue has in common.' },
]

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function RecommendationDeck(): JSX.Element {
    const [dismissed, setDismissed] = useState<string[]>([])
    const [index, setIndex] = useState(0)
    const shown = RECOMMENDATIONS.filter((recommendation) => !dismissed.includes(recommendation.title))
    if (shown.length === 0) {
        return <Text variant="muted">No recommendations left.</Text>
    }
    const position = Math.min(index, shown.length - 1)
    const current = shown[position]
    return (
        <Callout>
            <CalloutContent>
                <CalloutTitle>{current.title}</CalloutTitle>
                <CalloutDescription>{current.body}</CalloutDescription>
            </CalloutContent>
            <CalloutActions>
                <Text size="xs" variant="muted" className="tabular-nums">
                    {position + 1} of {shown.length}
                </Text>
                <Button
                    size="icon-sm"
                    aria-label="Previous recommendation"
                    onClick={() => setIndex((position - 1 + shown.length) % shown.length)}
                >
                    <IconChevronLeft />
                </Button>
                <Button
                    size="icon-sm"
                    aria-label="Next recommendation"
                    onClick={() => setIndex((position + 1) % shown.length)}
                >
                    <IconChevronRight />
                </Button>
            </CalloutActions>
            <CalloutClose
                aria-label={`Dismiss ${current.title}`}
                data-attr="dashboard-v2-example-dismiss-recommendation"
                onClick={() => setDismissed([...dismissed, current.title])}
            />
        </Callout>
    )
}
