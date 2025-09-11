import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { summarizeInsightQuery } from 'scenes/insights/summarizeInsight'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

export function BackToSource(): JSX.Element | null {
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    const { backToSourceQuery } = useValues(dataNodeLogic)

    if (!backToSourceQuery) {
        return null
    }

    const summary = summarizeInsightQuery(backToSourceQuery.source, {
        aggregationLabel,
        cohortsById,
        mathDefinitions,
    })

    return (
        <LemonButton
            tooltip={summary}
            type="secondary"
            onClick={() => router.actions.push(urls.insightNew({ query: backToSourceQuery }))}
        >
            &laquo; Back to {backToSourceQuery.source.kind?.replace('Query', '') ?? 'Insight'}
        </LemonButton>
    )
}
