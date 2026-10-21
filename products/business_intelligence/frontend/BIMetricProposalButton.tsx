import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { getBIMetricSnapshot } from './biCatalog'
import { biMetricProposalLogic } from './biMetricProposalLogic'
import { getBIVisualizationSource } from './biQueryResults'
import { biSceneLogic } from './biSceneLogic'

export function BIMetricProposalButton({ tabId }: { tabId: string }): JSX.Element {
    const { worksheet, name, lastRunQuery, dataNodeKey } = useValues(biSceneLogic({ tabId }))
    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic({
            key: dataNodeKey,
            query: getBIVisualizationSource(lastRunQuery ?? worksheet),
            autoLoad: !!lastRunQuery,
        })
    )
    const snapshot = getBIMetricSnapshot(worksheet, lastRunQuery, response, !responseLoading && !responseError)
    const { proposeMetric } = useActions(biMetricProposalLogic({ tabId, config: worksheet.config, snapshot, name }))
    return (
        <LemonButton
            size="small"
            onClick={proposeMetric}
            disabledReason={
                worksheet.source.connectionId
                    ? 'Catalog metrics currently support project and warehouse data'
                    : !snapshot
                      ? 'Run the current worksheet successfully before proposing its query'
                      : undefined
            }
            data-attr="bi-propose-metric"
        >
            Propose as catalog metric
        </LemonButton>
    )
}
