import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AttentionSubject, modelsOverviewLogic } from './modelsOverviewLogic'
import { subjectNextStep } from './subjectNextStep'

const STARTED_LABEL = 'Refresh started'

function RefreshButton({ savedQueryId, label }: { savedQueryId: string; label: string }): JSX.Element {
    const { startedRefreshSavedQueryIds } = useValues(modelsOverviewLogic)
    const { runDataWarehouseSavedQuery } = useActions(modelsOverviewLogic)
    const started = startedRefreshSavedQueryIds.includes(savedQueryId)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Button
                variant="outline"
                size="sm"
                disabled={started || undefined}
                onClick={() => runDataWarehouseSavedQuery(savedQueryId)}
                data-attr="models-overview-refresh"
            >
                {started ? STARTED_LABEL : label}
            </Button>
        </AccessControlAction>
    )
}

export function ModelsOverviewNextStep({ subject }: { subject: AttentionSubject }): JSX.Element | null {
    const nextStep = subjectNextStep(subject)
    if (!nextStep) {
        return null
    }
    if (nextStep.kind === 'refresh') {
        return <RefreshButton savedQueryId={nextStep.savedQueryId} label={nextStep.label} />
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
