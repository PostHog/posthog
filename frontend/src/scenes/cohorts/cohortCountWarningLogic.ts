import { connect, kea, key, path, props, selectors } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode } from '~/queries/schema/schema-general'
import { CohortType } from '~/types'

import type { cohortCountWarningLogicType } from './cohortCountWarningLogicType'

export type CohortCountWarningLogicProps = {
    cohort: CohortType
    query: DataTableNode
    dataNodeLogicKey: string
}

export const cohortCountWarningLogic = kea<cohortCountWarningLogicType>([
    props({} as CohortCountWarningLogicProps),
    key((props) => `cohort-count-warning-${props.cohort.id}-${props.dataNodeLogicKey}`),
    path(['scenes', 'cohorts', 'cohortCountWarningLogic']),

    connect((props: CohortCountWarningLogicProps) => ({
        values: [dataNodeLogic({ key: props.dataNodeLogicKey, query: props.query }), ['response']],
    })),

    selectors(({ props }) => ({
        shouldShowCountWarning: [
            (s) => [s.response],
            (response): boolean => {
                const { cohort } = props

                if (!cohort.count || cohort.is_calculating || cohort.id === 'new' || cohort.is_static) {
                    return false
                }

                if (!response) {
                    return false
                }

                if ((response as any)?.hasMore) {
                    return false
                }

                const displayedCount = (response as any)?.results?.length || 0
                return displayedCount !== cohort.count
            },
        ],
    })),
])
