import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconExtension } from 'lib/lemon-ui/icons'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { canInstallPlugins } from 'scenes/plugins/access'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { PluginInstallationType } from '~/types'

export function SideBarApps(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { hideSideBarMobile, setOpenAppMenu } = useActions(navigationLogic)
    const { openAppMenu } = useValues(navigationLogic)
    const { frontendApps, appConfigs } = useValues(frontendAppsLogic)
    const { currentLocation } = useValues(router)

    return (
        <>
            {Object.values(frontendApps).map(({ id, title }) => (
                <PageButton
                    key={id}
                    icon={<IconExtension />}
                    title={title || `App #${id}`}
                    identifier={currentLocation.pathname === urls.frontendApp(id) ? Scene.FrontendAppScene : 'nope'}
                    to={urls.frontendApp(id)}
                    sideAction={
                        canInstallPlugins(currentOrganization) &&
                        appConfigs[id]?.pluginType === PluginInstallationType.Source
                            ? {
                                  identifier: 'app-menu',
                                  onClick: () => setOpenAppMenu(openAppMenu === id ? null : id),
                                  dropdown: {
                                      visible: openAppMenu === id,
                                      onClickOutside: () => setOpenAppMenu(null),
                                      onClickInside: () => {
                                          setOpenAppMenu(null)
                                          hideSideBarMobile()
                                      },
                                      overlay: null,
                                  },
                              }
                            : undefined
                    }
                />
            ))}
        </>
    )
}
