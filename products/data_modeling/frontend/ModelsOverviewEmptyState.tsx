import { IconPlus } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { OverviewChecksStatus } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

export interface ModelsOverviewEmptyStateProps {
    checksStatus: OverviewChecksStatus
}

export function ModelsOverviewEmptyState({ checksStatus }: ModelsOverviewEmptyStateProps): JSX.Element {
    return (
        <Empty data-attr="models-overview-first-view">
            <EmptyHeader>
                <EmptyTitle>Create your first view</EmptyTitle>
                <EmptyDescription>Save a SQL query as a view to start building your models.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center gap-2">
                <AccessControlAction
                    resourceType={AccessControlResourceType.WarehouseObjects}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="primary"
                        render={<LinkPrimitive to={urls.sqlEditor({ source: 'view' })} />}
                        data-attr="models-overview-create-view"
                    >
                        <IconPlus />
                        Create view
                    </Button>
                </AccessControlAction>
                <Button
                    variant="outline"
                    render={<LinkPrimitive to={urls.models('data-quality')} />}
                    data-attr="models-overview-checks"
                >
                    {checksStatus === 'none' ? 'Set up checks' : 'View checks'}
                </Button>
            </EmptyContent>
        </Empty>
    )
}
