import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AttentionNextStep, modelsOverviewLogic } from './modelsOverviewLogic'
import { REFRESHING_LABEL, REFRESH_LABEL } from './overviewIssueCopy'

function RefreshButton({ savedQueryId, refreshing }: { savedQueryId: string; refreshing: boolean }): JSX.Element {
    const { requestRefresh } = useActions(modelsOverviewLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Button
                variant="outline"
                size="sm"
                disabled={refreshing || undefined}
                onClick={() => requestRefresh(savedQueryId)}
                data-attr="models-overview-refresh"
            >
                {refreshing ? REFRESHING_LABEL : REFRESH_LABEL}
            </Button>
        </AccessControlAction>
    )
}

export function ModelsOverviewNextStep({ nextStep }: { nextStep: AttentionNextStep | null }): JSX.Element | null {
    if (!nextStep) {
        return null
    }
    if (nextStep.kind === 'refresh') {
        return <RefreshButton savedQueryId={nextStep.savedQueryId} refreshing={nextStep.refreshing} />
    }
    return (
        <Button
            variant="outline"
            size="sm"
            render={<LinkPrimitive to={nextStep.href} />}
            data-attr="models-overview-next-step"
        >
            {nextStep.label}
        </Button>
    )
}
