import { Fragment, ReactNode } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Badge, Card, CardDescription, CardHeader, CardTitle, Text } from '@posthog/quill'

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
        <div className="flex w-full flex-col gap-3 text-left">
            <ol
                aria-label="How metrics work"
                className="m-0 flex list-none flex-col items-stretch gap-2 p-0 @min-[48rem]/main-content:flex-row"
            >
                {STEPS.map(({ title, status, description }, index) => (
                    <Fragment key={title}>
                        {index > 0 && (
                            <li aria-hidden className="flex shrink-0 items-center justify-center text-muted-foreground">
                                <IconArrowRight className="size-4 rotate-90 @min-[48rem]/main-content:rotate-0" />
                            </li>
                        )}
                        <li className="min-w-0 flex-1">
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
                    </Fragment>
                ))}
            </ol>
            <Text size="xs" variant="muted" render={<div />} className="flex flex-wrap items-center gap-1">
                <Badge variant="destructive">Drifted</Badge>
                <span>
                    means the source insight changed after the metric was saved. Agents still use it, with a warning.
                </span>
            </Text>
        </div>
    )
}
