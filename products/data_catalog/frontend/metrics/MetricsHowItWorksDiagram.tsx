import { ReactNode } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Badge, Card, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

interface Step {
    title: string
    status?: ReactNode
    description: string
}

// The status badges match the ones in the metrics table, so the diagram teaches what the table shows.
const STEPS: Step[] = [
    {
        title: 'Define',
        description: 'Name a number your team uses, like revenue or active users, and write the query behind it.',
    },
    {
        title: 'Review',
        status: <Badge variant="warning">Proposed</Badge>,
        description: 'A teammate checks the definition. Agents can already use it, with a warning.',
    },
    {
        title: 'Use',
        status: <Badge variant="success">Approved</Badge>,
        description: 'PostHog AI and agents compute the number from this definition, so everyone gets the same answer.',
    },
]

export function MetricsHowItWorksDiagram(): JSX.Element {
    return (
        <ol
            aria-label="How metrics work"
            className="m-0 flex w-full list-none flex-col items-stretch gap-8 p-0 text-left @min-[48rem]/main-content:flex-row"
        >
            {STEPS.map(({ title, status, description }, index) => (
                <li key={title} className="relative min-w-0 flex-1">
                    {/* Inside the step's own item, so a screen reader counts three steps, not five items. */}
                    {index > 0 && (
                        <span
                            aria-hidden
                            className="absolute -top-6 left-1/2 flex -translate-x-1/2 text-muted-foreground @min-[48rem]/main-content:top-1/2 @min-[48rem]/main-content:-left-6 @min-[48rem]/main-content:translate-x-0 @min-[48rem]/main-content:-translate-y-1/2"
                        >
                            <IconArrowRight className="size-4 rotate-90 @min-[48rem]/main-content:rotate-0" />
                        </span>
                    )}
                    <Card size="sm" className="h-full">
                        <CardHeader>
                            <CardTitle className="flex flex-wrap items-center gap-2">
                                <span>
                                    {index + 1}. {title}
                                </span>
                                {status}
                            </CardTitle>
                            <CardDescription>{description}</CardDescription>
                        </CardHeader>
                    </Card>
                </li>
            ))}
        </ol>
    )
}
