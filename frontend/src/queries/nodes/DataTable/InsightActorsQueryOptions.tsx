import { useMountedLogic, useValues } from 'kea'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightActorsQueryOptionsLogic } from '~/queries/nodes/DataTable/insightActorsQueryOptionsLogic'
import { InsightActorsQuery } from '~/queries/schema'

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
            {Object.entries(insightActorsQueryOptions)
                .filter(([, value]) => !!value)
                .map(([key, options]) => (
                    <div key={key}>
                        <LemonSelect
                            fullWidth
                            className="min-w-32"
                            placeholder={key}
                            value={query?.[key] ?? null}
                            onChange={(v) =>
                                setQuery?.({
                                    ...query,
                                    [key]: v,
                                })
                            }
                            options={options}
                        />
                    </div>
                ))}
        </>
    ) : null
}
