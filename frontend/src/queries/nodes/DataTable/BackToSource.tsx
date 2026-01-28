import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'

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

    const insightSummary = summarizeInsightQuery(backToSourceQuery.source, {
        aggregationLabel,
        cohortsById,
        mathDefinitions,
    })
    const summary = `Viewing actors query based on insight: ${insightSummary}`

    return (
        <LemonButton
            tooltip={summary}
            type="primary"
            onClick={() => router.actions.push(urls.insightNew({ query: backToSourceQuery }))}
            size="small"
            className="mr-2"
        >
            <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary mr-1" /> View source insight
        </LemonButton>
    )
}
