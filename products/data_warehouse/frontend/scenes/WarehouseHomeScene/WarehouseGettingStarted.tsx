import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCheckCircle } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Heading,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { warehouseHomeLogic, WarehouseStepState } from './warehouseHomeLogic'
import { WarehouseMcpSetup } from './WarehouseMcpSetup'

type WarehouseStep = 'connect_source' | 'answer_question' | 'save_insight'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

// `kind` is the connector name the new source page expects.
const POPULAR_SOURCES = [
    { label: 'Stripe', kind: 'Stripe' },
    { label: 'HubSpot', kind: 'Hubspot' },
    { label: 'Supabase', kind: 'Supabase' },
    { label: 'Zendesk', kind: 'Zendesk' },
    { label: 'Postgres', kind: 'Postgres' },
    { label: 'Google Ads', kind: 'GoogleAds' },
]

function captureStepClick(step: WarehouseStep, target: string, state?: WarehouseStepState): void {
    posthog.capture('warehouse getting started clicked', { step, target, done: state === 'done' })
}

interface StepCardProps {
    index: number
    // Steps without a state have no signal for "done", so they always show their number.
    state?: WarehouseStepState
    title: string
    description: string
    children?: React.ReactNode
    actions: React.ReactNode
}

function StepCard({ index, state, title, description, children, actions }: StepCardProps): JSX.Element {
    return (
        <Card>
            <CardHeader>
                <div className="flex items-center gap-2">
                    {state === 'loading' ? (
                        <Skeleton className="size-4" />
                    ) : state === 'done' ? (
                        <IconCheckCircle className="size-4 text-success-foreground" aria-label="Done" />
                    ) : (
                        <Text size="sm" weight="medium" variant="muted" render={<span />}>
                            {index}
                        </Text>
                    )}
                    <CardTitle>{title}</CardTitle>
                </div>
                <CardDescription>{description}</CardDescription>
            </CardHeader>
            {children && <CardContent>{children}</CardContent>}
            <CardFooter className="mt-auto flex-wrap gap-2">{actions}</CardFooter>
        </Card>
    )
}

export function WarehouseGettingStarted(): JSX.Element {
    const { sourceStep, viewStep } = useValues(warehouseHomeLogic)

    return (
        <section aria-labelledby="warehouse-getting-started" className="flex flex-col gap-3">
            <Heading render={<h2 id="warehouse-getting-started" />} size="base" className="m-0">
                Getting started
            </Heading>
            <div className="flex flex-col gap-4">
                <div className="grid gap-4 @3xl/warehouse-home:grid-cols-3">
                    <StepCard
                        index={1}
                        state={sourceStep}
                        title="Connect a source"
                        description="Bring in data from your payments tool, CRM, support desk, ad platforms and databases. Sync into your warehouse on a schedule, next to your PostHog events."
                        actions={
                            <Button
                                size="sm"
                                variant={sourceStep === 'done' ? 'default' : 'primary'}
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.dataWarehouseSourceNew()} />}
                                data-attr="warehouse-home-connect-source"
                                onClick={() => captureStepClick('connect_source', 'add_source', sourceStep)}
                            >
                                Connect a source
                            </Button>
                        }
                    >
                        <div className="flex flex-wrap gap-2">
                            {POPULAR_SOURCES.map((source) => (
                                <Button
                                    key={source.kind}
                                    size="xs"
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.dataWarehouseSourceNew(source.kind)} />}
                                    data-attr={`warehouse-home-connect-source-${source.kind.toLowerCase()}`}
                                    onClick={() => captureStepClick('connect_source', source.kind, sourceStep)}
                                >
                                    {source.label}
                                </Button>
                            ))}
                        </div>
                    </StepCard>
                    <StepCard
                        index={2}
                        state={viewStep}
                        title="Answer a question"
                        description="Query your PostHog and business data together. Start from a question below and run the skill, ask PostHog AI in plain English, or write the SQL yourself."
                        actions={
                            <>
                                <Button
                                    size="sm"
                                    variant="primary"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.ai()} />}
                                    data-attr="warehouse-home-ask-ai"
                                    onClick={() => captureStepClick('answer_question', 'ask_ai', viewStep)}
                                >
                                    Ask PostHog AI
                                </Button>
                                <Button
                                    size="sm"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.sqlEditor()} />}
                                    data-attr="warehouse-home-create-view"
                                    onClick={() => captureStepClick('answer_question', 'sql_editor', viewStep)}
                                >
                                    Open the SQL editor
                                </Button>
                            </>
                        }
                    />
                    <StepCard
                        index={3}
                        title="Save it as an insight"
                        description="Save your answer as an insight so it refreshes on a schedule and you can keep going back to it. Add it to a dashboard, share it with your team, or send the results to your CRM."
                        actions={
                            <>
                                <Button
                                    size="sm"
                                    variant="primary"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.insightNew()} />}
                                    data-attr="warehouse-home-new-insight"
                                    onClick={() => captureStepClick('save_insight', 'new_insight')}
                                >
                                    New insight
                                </Button>
                                <Button
                                    size="sm"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.dashboards()} />}
                                    data-attr="warehouse-home-dashboards"
                                    onClick={() => captureStepClick('save_insight', 'dashboards')}
                                >
                                    Go to dashboards
                                </Button>
                            </>
                        }
                    />
                </div>
                <WarehouseMcpSetup />
            </div>
        </section>
    )
}
