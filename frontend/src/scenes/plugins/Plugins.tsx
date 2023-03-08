import './Plugins.scss'
import { useEffect } from 'react'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { RepositoryTab } from 'scenes/plugins/tabs/repository/RepositoryTab'
import { InstalledTab } from 'scenes/plugins/tabs/installed/InstalledTab'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from './pluginsLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'
import { AdvancedTab } from 'scenes/plugins/tabs/advanced/AdvancedTab'
import { canGloballyManagePlugins, canInstallPlugins, canViewPlugins } from './access'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonTag } from '@posthog/lemon-ui'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

export const scene: SceneExport = {
    component: Plugins,
    logic: pluginsLogic,
}

const BetaTag = (): JSX.Element => (
    <LemonTag type="warning" className="uppercase" style={{ verticalAlign: '0.125em', marginLeft: 6 }}>
        BETA
    </LemonTag>
)

export function Plugins(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    useEffect(() => {
        if (!canViewPlugins(user?.organization)) {
            window.location.href = '/'
        }
    }, [user])

    if (!user || !canViewPlugins(user?.organization)) {
        return null
    }

    return (
        <div className="plugins-scene">
            <PageHeader
                title="Apps"
                caption={
                    <>
                        Apps enable you to extend PostHog's core data processing functionality.
                        <br />
                        Make use of verified apps from the{' '}
                        <a href="https://posthog.com/apps" target="_blank">
                            App Library
                        </a>{' '}
                        – or{' '}
                        <a href="https://posthog.com/docs/apps/build" target="_blank">
                            build your own
                        </a>
                        .
                    </>
                }
                tabbedPage
            />
            <LemonTabs
                data-attr="apps-tabs"
                activeKey={pluginTab}
                onChange={(newKey) => setPluginTab(newKey)}
                tabs={[
                    { key: PluginTab.Installed, label: 'Installed', content: <InstalledTab /> },
                    canGloballyManagePlugins(user.organization) && {
                        key: PluginTab.Repository,
                        label: 'Repository',
                        content: <RepositoryTab />,
                    },
                    {
                        key: PluginTab.History,
                        label: (
                            <>
                                <span>History</span>
                                <BetaTag />
                            </>
                        ),
                        content: <ActivityLog scope={ActivityScope.PLUGIN} />,
                    },
                    canInstallPlugins(user.organization) && {
                        key: PluginTab.Advanced,
                        label: 'Advanced',
                        content: <AdvancedTab />,
                    },
                ]}
            />
            <PluginDrawer />
        </div>
    )
}
