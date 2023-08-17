import { LogsDrawer } from 'scenes/plugins/plugin/LogsDrawer'
import { DisabledPluginSection } from '../installed/sections/DisabledPluginsSection'
import { EnabledPluginSection } from '../installed/sections/EnabledPluginsSection'
import { UpgradeSection } from '../installed/sections/UpgradeSection'
import { RepositoryApps } from '../repository/RepositoryTab'
import { canGloballyManagePlugins } from 'scenes/plugins/access'
import { userLogic } from 'scenes/userLogic'
import { useValues } from 'kea'
import { AppsList } from './AppsList'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'

export function AppsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    return (
        <div className="space-y-4">
            <AppsList />

            <UpgradeSection />
            <EnabledPluginSection />
            <DisabledPluginSection />
            {canGloballyManagePlugins(user?.organization) && <RepositoryApps />}
            <LogsDrawer />
            <PluginDrawer />
        </div>
    )
}
