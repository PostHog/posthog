import { connect, kea, key, path, props, selectors } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ActorsQuery, ActorsQueryResponse, DataTableNode } from '~/queries/schema/schema-general'
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
            (s, p) => [s.response, p.query],
            (response: ActorsQueryResponse, query: DataTableNode): boolean => {
                const { cohort } = props

                if (!cohort.count || cohort.is_calculating || cohort.id === 'new' || cohort.is_static) {
                    return false
                }

                if (!response) {
                    return false
                }

                if (response.hasMore) {
                    return false
                }

                const source = query.source as ActorsQuery
                if (source.search) {
                    return false
                }

                if (source.properties) {
                    if (Array.isArray(source.properties) && source.properties.length > 0) {
                        return false
                    }

                    if (!Array.isArray(source.properties) && source.properties.values?.length > 0) {
                        return false
                    }
                }

                const displayedCount = (response as any)?.results?.length || 0
                return displayedCount !== cohort.count
            },
        ],
    })),
])
