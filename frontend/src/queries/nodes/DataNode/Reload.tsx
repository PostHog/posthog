import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconRefresh } from 'lib/components/icons'

export function Reload(): JSX.Element {
    const { responseLoading } = useValues(dataNodeLogic)
    const { loadData } = useActions(dataNodeLogic)

    return (
        <LemonButton
            type="secondary"
            onClick={() => {
                loadData()
            }}
            loading={responseLoading}
            icon={<IconRefresh />}
        >
            {responseLoading ? 'Loading' : 'Reload'}
        </LemonButton>
    )
}
