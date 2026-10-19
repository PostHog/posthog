import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Progress,
    Skeleton,
} from '@posthog/quill'

import { warehouseHomeLogic, WarehouseStepState } from './warehouseHomeLogic'

interface ChecklistStep {
    title: string
    description: string
    state: WarehouseStepState
}

export function WarehouseFirstAnswerChecklist(): JSX.Element {
    const { sourceStep, viewStep } = useValues(warehouseHomeLogic)

    // Only steps the app can detect are listed, so the progress bar can reach the end.
    const steps: ChecklistStep[] = [
        {
            title: 'Collect event data using PostHog',
            description: 'Use product analytics, session replay, logs, and more.',
            state: 'done',
        },
        {
            title: 'Connect an external source',
            description: 'Stripe, HubSpot, Zendesk, or one of hundreds more.',
            state: sourceStep,
        },
        {
            title: 'Answer a question',
            description: 'Query your PostHog and business data together.',
            state: viewStep,
        },
    ]
    const loading = steps.some((step) => step.state === 'loading')
    const doneCount = steps.filter((step) => step.state === 'done').length

    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Get your first answer</CardTitle>
                <CardDescription>
                    {loading ? (
                        <Skeleton className="h-4 w-24" />
                    ) : (
                        <span translate="no">
                            {doneCount} of {steps.length} done
                        </span>
                    )}
                </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {loading ? (
                    <Skeleton className="h-1.5 w-full" />
                ) : (
                    <Progress value={(doneCount / steps.length) * 100} aria-label="Setup progress" />
                )}
                <ItemGroup>
                    {steps.map((step) => (
                        <Item key={step.title} size="xs">
                            <ItemMedia variant="icon">
                                {step.state === 'loading' ? (
                                    <Skeleton className="size-4" />
                                ) : step.state === 'done' ? (
                                    <IconCheckCircle className="text-success-foreground" aria-label="Done" />
                                ) : (
                                    <span className="size-4 rounded-full border border-border" aria-label="Not done" />
                                )}
                            </ItemMedia>
                            <ItemContent>
                                <ItemTitle className={step.state === 'done' ? 'text-muted-foreground' : undefined}>
                                    {step.title}
                                </ItemTitle>
                                <ItemDescription>{step.description}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ))}
                </ItemGroup>
            </CardContent>
        </Card>
    )
}
