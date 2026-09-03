import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { DataTableNode } from '~/queries/schema/schema-general'
import { CohortType } from '~/types'

import { cohortCountWarningLogic } from './cohortCountWarningLogic'

/**
 * Warns that the persons table shows fewer people than the cohort count.
 *
 * Only render this for a saved cohort. It connects `dataNodeLogic`, which runs the actors query
 * as soon as it mounts, and a draft cohort has no id to query on.
 */
export function CohortCountWarning({
    cohort,
    query,
    dataNodeLogicKey,
}: {
    cohort: CohortType
    query: DataTableNode
    dataNodeLogicKey: string
}): JSX.Element | null {
    const { shouldShowCountWarning } = useValues(cohortCountWarningLogic({ cohort, query, dataNodeLogicKey }))

    if (!shouldShowCountWarning) {
        return null
    }

    return (
        <Tooltip title="The displayed number of persons is less than the cohort count due to deleted persons. This is expected behavior for dynamic cohorts where persons may be deleted after being counted.">
            <IconWarning className="text-warning ml-2" />
        </Tooltip>
    )
}
