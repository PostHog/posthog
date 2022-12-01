import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconRefresh } from 'lib/components/icons'
import { Spinner } from 'lib/components/Spinner/Spinner'

export function LoadNew(): JSX.Element {
    const { responseLoading } = useValues(dataNodeLogic)
    const { loadNewData } = useActions(dataNodeLogic)

    return (
        <LemonButton
            type="secondary"
            onClick={loadNewData}
            loading={responseLoading}
            icon={responseLoading ? <Spinner /> : <IconRefresh />}
        >
            Load new events
        </LemonButton>
    )
}
