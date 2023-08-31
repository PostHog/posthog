import { CaretRightOutlined } from '@ant-design/icons'
import { Empty, Skeleton } from 'antd'
import { Subtitle } from 'lib/components/PageHeader'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginTab } from 'scenes/plugins/types'
import { canGloballyManagePlugins } from 'scenes/plugins/access'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from '@posthog/lemon-ui'

export function PluginsEmptyState(): JSX.Element {
    const { setPluginTab } = useActions(pluginsLogic)
    const { loading } = useValues(pluginsLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            {loading ? (
                <>
                    <Subtitle
                        subtitle={
                            <>
                                {' '}
                                <CaretRightOutlined /> {'Enabled apps'}{' '}
                            </>
                        }
                        buttons={<Skeleton.Button style={{ width: 150 }} />}
                    />
                    <PluginLoading />
                </>
            ) : (
                <>
                    <Subtitle subtitle="Installed apps" />
                    <div className="mt-4">
                        <Empty description={<span>You haven't installed any apps yet</span>}>
                            {canGloballyManagePlugins(user?.organization) && (
                                <LemonButton
                                    onClick={() => setPluginTab(PluginTab.Repository)}
                                    status="muted"
                                    type="secondary"
                                >
                                    Open the App Repository
                                </LemonButton>
                            )}
                        </Empty>
                    </div>
                </>
            )}
        </>
    )
}
