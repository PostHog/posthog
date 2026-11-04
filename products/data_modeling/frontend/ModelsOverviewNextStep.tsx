import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { nodeEndpointModel } from './endpointModelName'
import { AttentionSubject, modelsOverviewLogic } from './modelsOverviewLogic'
import { REFRESH_LABELS, nextStepLabel } from './overviewIssueCopy'
import { subjectHref } from './subjectHref'

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
    const { node, materialization } = subject
    const kind = materialization?.kind
    if (node?.saved_query_id && !nodeEndpointModel(node) && (kind === 'failed' || kind === 'behind')) {
        return <RefreshButton savedQueryId={node.saved_query_id} label={REFRESH_LABELS[kind]} />
    }

    const href = subjectHref(subject)
    if (!href) {
        return null
    }
    return (
        <Button variant="outline" size="sm" render={<LinkPrimitive to={href} />} data-attr="models-overview-next-step">
            {nextStepLabel(subject)}
        </Button>
    )
}
