import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { summarizeInsightQuery } from 'scenes/insights/summarizeInsight'
import { teamLogic } from 'scenes/teamLogic'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode } from '~/queries/schema'

interface ReturnToSourceProps {
    setQuery?: (query: DataTableNode) => void
}

export function BackToSource({ setQuery }: ReturnToSourceProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

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

    if (!setQuery || !currentTeam) {
        return null
    }

    return (
        <LemonButton
            tooltip={summary}
            type="secondary"
            status="primary-alt"
            onClick={() =>
                router.actions.push(urls.insightNew(undefined, undefined, JSON.stringify(backToSourceQuery)))
            }
        >
            &laquo; Back to {backToSourceQuery.source.kind ?? 'Insight'}
        </LemonButton>
    )
}
