import * as float from '@posthog/brand/hoggies/png/float'
import { IconCheckCircle, IconCode, IconGitBranch, IconPlus, IconRefresh } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { OverviewChecksStatus } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { healthyMessage } from './healthyMessage'

const HedgehogFloat = pngHoggie(float)
const HEADING_ID = 'models-overview-empty-state-heading'
const STEPS_HEADING_ID = 'models-overview-first-view-steps-heading'

const STEPS = [
    {
        icon: IconCode,
        title: 'Save a query as a view',
        description: 'Query a view like a table from insights, the SQL editor, or other views.',
    },
    {
        icon: IconRefresh,
        title: 'Materialize slow views',
        description: 'Store the results on a schedule, so reading a view does not rerun its query.',
    },
    {
        icon: IconGitBranch,
        title: 'Follow the lineage',
        description: 'See which tables a view reads and which models depend on it.',
    },
    {
        icon: IconCheckCircle,
        title: 'Check the results',
        description: 'Add data quality checks that test your models after each refresh.',
    },
]

export type ModelsOverviewEmptyStateVariant = 'first-view' | 'healthy'

const FIRST_VIEW_DESCRIPTION =
    'A view is a saved SQL query. Build views on your data, materialize the slow ones, and check that their results stay correct.'

export interface ModelsOverviewEmptyStateProps {
    variant: ModelsOverviewEmptyStateVariant
    checksStatus: OverviewChecksStatus
    checksTruncated?: boolean
}

function DataModelingSteps(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 id={STEPS_HEADING_ID} className="m-0" />}>
                How data modeling works
            </Heading>
            <ItemGroup aria-labelledby={STEPS_HEADING_ID} className="grid gap-2 @min-[40rem]/main-content:grid-cols-2">
                {STEPS.map(({ icon: Icon, title, description }) => (
                    <Item key={title} variant="outline" render={<div role="listitem" />}>
                        <ItemMedia variant="icon">
                            <Icon />
                        </ItemMedia>
                        <ItemContent>
                            <ItemTitle>{title}</ItemTitle>
                            <ItemDescription>{description}</ItemDescription>
                        </ItemContent>
                    </Item>
                ))}
            </ItemGroup>
        </div>
    )
}

export function ModelsOverviewEmptyState({
    variant,
    checksStatus,
    checksTruncated = false,
}: ModelsOverviewEmptyStateProps): JSX.Element {
    const firstView = variant === 'first-view'

    return (
        <Card
            role="region"
            aria-labelledby={HEADING_ID}
            data-attr={firstView ? 'models-overview-first-view' : 'models-overview-healthy'}
        >
            <CardContent className="flex flex-col gap-6">
                <div className="flex flex-col items-start gap-4 @min-[40rem]/main-content:flex-row @min-[40rem]/main-content:items-center">
                    <HedgehogFloat className="w-28 shrink-0 self-center @min-[40rem]/main-content:w-36" />
                    <div className="flex min-w-0 flex-col gap-2">
                        <Heading size="lg" render={<h2 id={HEADING_ID} className="m-0" />}>
                            {firstView ? 'Create your first view' : 'Nothing needs attention'}
                        </Heading>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {firstView ? FIRST_VIEW_DESCRIPTION : healthyMessage(checksStatus, checksTruncated)}
                        </Text>
                        <div className="flex flex-wrap gap-2 pt-2">
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <Button
                                    elevated
                                    variant="primary"
                                    render={<LinkPrimitive to={urls.sqlEditor({ source: 'view' })} />}
                                    data-attr="models-overview-create-view"
                                >
                                    <IconPlus />
                                    Create view
                                </Button>
                            </AccessControlAction>
                            <Button
                                elevated
                                variant="outline"
                                render={<LinkPrimitive to={urls.models('data-quality')} />}
                                data-attr="models-overview-checks"
                            >
                                {checksStatus === 'none' ? 'Set up checks' : 'View checks'}
                            </Button>
                            {!firstView && (
                                <Button
                                    render={<LinkPrimitive to={urls.models('lineage')} />}
                                    data-attr="models-overview-lineage"
                                >
                                    View lineage
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
                {firstView && <DataModelingSteps />}
            </CardContent>
        </Card>
    )
}
