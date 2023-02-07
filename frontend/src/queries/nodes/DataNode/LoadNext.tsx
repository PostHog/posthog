import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DataNode } from '~/queries/schema'
import { isPersonsNode } from '~/queries/utils'

interface LoadNextProps {
    query: DataNode
}
export function LoadNext({ query }: LoadNextProps): JSX.Element {
    const { nextDataLoading } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    return (
        <LemonButton type="primary" onClick={loadNextData} loading={nextDataLoading} className="my-8 mx-auto">
            Load more {isPersonsNode(query) ? 'people' : 'events'}
        </LemonButton>
    )
}
