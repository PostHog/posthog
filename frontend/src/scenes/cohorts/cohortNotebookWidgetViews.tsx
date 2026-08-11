import { useValues } from 'kea'

import { IconPeople } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { cohortEditLogic } from './cohortEditLogic'

export type CohortNotebookWidgetAttributes = {
    id: number
    view?: string
}

function CohortSummary({ attributes }: NotebookNodeProps<CohortNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { cohort, cohortLoading, cohortMissing } = useValues(cohortEditLogic({ id }))

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    if (cohortLoading || !cohort) {
        return (
            <div className="flex items-center gap-2 p-3">
                <IconPeople className="text-lg" />
                <LemonSkeleton className="h-6 flex-1" />
            </div>
        )
    }

    return (
        <div className="p-3 text-xs text-secondary">
            {cohort.count} {cohort.count === 1 ? 'person' : 'persons'}
        </div>
    )
}

export const COHORT_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<CohortNotebookWidgetAttributes, 'Cohort'>(
    'Cohort',
    {
        summary: CohortSummary,
    }
)
