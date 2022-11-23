import { LoadingOutlined, ReloadOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'

export function ReloadQuery(): JSX.Element {
    const { responseLoading } = useValues(dataNodeLogic)
    const { loadData } = useActions(dataNodeLogic)

    return (
        <LemonButton
            type="secondary"
            onClick={loadData}
            disabled={responseLoading}
            icon={responseLoading ? <LoadingOutlined /> : <ReloadOutlined />}
        >
            {responseLoading ? 'Loading' : 'Reload'}
        </LemonButton>
    )
}
