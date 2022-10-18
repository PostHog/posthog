import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { PluginUpdateStatusType } from '../types'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { CheckOutlined, CloudDownloadOutlined } from '@ant-design/icons'

interface PluginUpdateButtonProps {
    updateStatus: PluginUpdateStatusType | undefined
    pluginId: number
    rearranging: boolean | undefined
}

export const PluginUpdateButton = ({ updateStatus, pluginId, rearranging }: PluginUpdateButtonProps): JSX.Element => {
    const { editPlugin, updatePlugin } = useActions(pluginsLogic)
    const { pluginsUpdating } = useValues(pluginsLogic)
    return (
        <Button
            type={updateStatus?.updated ? 'default' : 'primary'}
            className="padding-under-500"
            onClick={() => (updateStatus?.updated ? editPlugin(pluginId) : updatePlugin(pluginId))}
            loading={pluginsUpdating.includes(pluginId)}
            icon={updateStatus?.updated ? <CheckOutlined /> : <CloudDownloadOutlined />}
            disabled={rearranging}
            data-attr="plugin-update"
        >
            <span className="show-over-500">{updateStatus?.updated ? 'Updated' : 'Update'}</span>
        </Button>
    )
}
