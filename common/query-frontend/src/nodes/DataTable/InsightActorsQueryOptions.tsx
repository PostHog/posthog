import { useMountedLogic, useValues } from 'kea'

import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { isKeyOf } from 'lib/utils'
import { cleanedInsightActorsQueryOptions } from '@posthog/query-frontend/persons-modal/persons-modal-utils'

import { dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import { insightActorsQueryOptionsLogic } from '@posthog/query-frontend/nodes/DataTable/insightActorsQueryOptionsLogic'
import { InsightActorsQuery } from '@posthog/query-frontend/schema/schema-general'

interface InsightActorsQueryOptionsProps {
    query: InsightActorsQuery
    setQuery?: (query: InsightActorsQuery) => void
}
export function InsightActorsQueryOptions({ setQuery, query }: InsightActorsQueryOptionsProps): JSX.Element | null {
    const localDataNodeLogic = useMountedLogic(dataNodeLogic)
    const { insightActorsQueryOptions } = useValues(
        insightActorsQueryOptionsLogic({
            key: localDataNodeLogic.key,
            query: query,
        })
    )

    return query && insightActorsQueryOptions ? (
        <>
            {cleanedInsightActorsQueryOptions(insightActorsQueryOptions, query).map(([key, options]) => (
                <div key={key}>
                    <LemonSelect
                        fullWidth
                        className="min-w-32"
                        placeholder={key}
                        value={isKeyOf(key, query) && !Array.isArray(query[key]) ? query[key] : null}
                        onChange={(v) =>
                            setQuery?.({
                                ...query,
                                [key]: v,
                            })
                        }
                        options={options as LemonSelectOptions<any>}
                    />
                </div>
            ))}
        </>
    ) : null
}
