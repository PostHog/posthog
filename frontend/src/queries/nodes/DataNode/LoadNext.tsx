import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DataNode } from '~/queries/schema'
import { isPersonsNode, isPersonsQuery } from '~/queries/utils'

interface LoadNextProps {
    query: DataNode
}
export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { nextDataLoading } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    return (
        <div className="m-2 flex items-center">
            <LemonButton onClick={loadNextData} loading={nextDataLoading} fullWidth center>
                Load more {isPersonsNode(query) || isPersonsQuery(query) ? 'people' : 'events'}
            </LemonButton>
        </div>
    )
}
