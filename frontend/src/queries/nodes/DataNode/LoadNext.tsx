import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonButton } from 'lib/components/LemonButton'

export function LoadNext(): JSX.Element {
    const { responseLoading } = useValues(dataNodeLogic)
    const { loadNextData } = useActions(dataNodeLogic)

    return (
        <LemonButton type="primary" onClick={loadNextData} loading={responseLoading} className="my-8 mx-auto">
            Load more events
        </LemonButton>
    )
}
