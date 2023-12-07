import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode } from '~/queries/schema'
import { isPersonsNode, isPersonsQuery } from '~/queries/utils'

interface LoadNextProps {
    query: DataNode
}
export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { nextDataLoading, numberOfRows } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    return (
        <div className="m-2 flex items-center">
            <LemonButton onClick={loadNextData} loading={nextDataLoading} fullWidth center>
                Showing {numberOfRows} {isPersonsNode(query) || isPersonsQuery(query) ? 'people' : 'events'}. Click to
                load more.
            </LemonButton>
        </div>
    )
}
