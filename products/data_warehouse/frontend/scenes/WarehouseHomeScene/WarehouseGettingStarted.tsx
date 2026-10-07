import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCheckCircle } from '@posthog/icons'
import {
    Button,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { warehouseHomeLogic, WarehouseStepState } from './warehouseHomeLogic'

type WarehouseStep = 'connect_source' | 'create_view' | 'explore'

interface StepAction {
    label: string
    to: string
    dataAttr: string
}

interface StepRowProps {
    step: WarehouseStep
    index: number
    state: WarehouseStepState
    title: string
    description: string
    actions: StepAction[]
}

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

function StepRow({ step, index, state, title, description, actions }: StepRowProps): JSX.Element {
    const done = state === 'done'
    return (
        <Item variant="outline">
            <ItemMedia variant="icon">
                {state === 'loading' ? (
                    <Skeleton className="size-4" />
                ) : done ? (
                    <IconCheckCircle />
                ) : (
                    <Text size="sm" weight="medium" render={<span />}>
                        {index}
                    </Text>
                )}
            </ItemMedia>
            <ItemContent>
                <ItemTitle>{title}</ItemTitle>
                <ItemDescription>{description}</ItemDescription>
            </ItemContent>
            <ItemActions className="flex-wrap">
                {actions.map((action) => (
                    <Button
                        key={action.dataAttr}
                        variant={done ? 'default' : 'primary'}
                        nativeButton={false}
                        render={<LinkPrimitive to={action.to} />}
                        data-attr={action.dataAttr}
                        onClick={() => {
                            posthog.capture('warehouse getting started clicked', { step, done })
                        }}
                    >
                        {action.label}
                    </Button>
                ))}
            </ItemActions>
        </Item>
    )
}

export function WarehouseGettingStarted(): JSX.Element {
    const { sourceStep, viewStep } = useValues(warehouseHomeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const biMode = !!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE]

    const exploreActions: StepAction[] = [
        { label: 'Open notebooks', to: urls.notebooks(), dataAttr: 'warehouse-home-open-notebooks' },
    ]
    if (biMode) {
        exploreActions.push({ label: 'Open BI', to: urls.businessIntelligence(), dataAttr: 'warehouse-home-open-bi' })
    }

    return (
        <section aria-labelledby="warehouse-getting-started" className="flex flex-col gap-2">
            <Heading render={<h2 id="warehouse-getting-started" />} size="base" className="m-0">
                Getting started
            </Heading>
            <ItemGroup className="gap-2">
                <StepRow
                    step="connect_source"
                    index={1}
                    state={sourceStep}
                    title="Connect a source"
                    description="Import data from tools like Stripe, Hubspot or Postgres."
                    actions={[
                        {
                            label: 'Add source',
                            to: urls.dataWarehouseSourceNew(),
                            dataAttr: 'warehouse-home-connect-source',
                        },
                    ]}
                />
                <StepRow
                    step="create_view"
                    index={2}
                    state={viewStep}
                    title="Create a view"
                    description="Write SQL that joins and cleans your data into a view you can reuse."
                    actions={[
                        { label: 'Open SQL editor', to: urls.sqlEditor(), dataAttr: 'warehouse-home-create-view' },
                    ]}
                />
                <StepRow
                    step="explore"
                    index={3}
                    // Exploring has no completion signal, so it is always open.
                    state="todo"
                    title="Explore your data"
                    description={`Analyze your tables in a notebook${biMode ? ' or with BI' : ''}.`}
                    actions={exploreActions}
                />
            </ItemGroup>
        </section>
    )
}
