import { IconExtension } from 'lib/components/icons'
import { urls } from 'scenes/urls'
import { Scene } from 'scenes/sceneTypes'
import { canInstallPlugins } from 'scenes/plugins/access'
import { LemonButton } from 'lib/components/LemonButton'
import { PluginSource } from 'scenes/plugins/source/PluginSource'
import React from 'react'
import { useActions, useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { router } from 'kea-router'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { PluginInstallationType } from 'scenes/plugins/types'

export function SideBarApps(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { hideSideBarMobile, openAppSourceEditor, closeAppSourceEditor, setOpenAppMenu } = useActions(navigationLogic)
    const { appSourceEditor, openAppMenu } = useValues(navigationLogic)
    const { frontendApps, appConfigs } = useValues(frontendAppsLogic)
    const { currentLocation } = useValues(router)

    return (
        <>
            {Object.values(frontendApps).map(({ id, pluginId, title }) => (
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
                                  popup: {
                                      visible: openAppMenu === id,
                                      onClickOutside: () => setOpenAppMenu(null),
                                      onClickInside: () => {
                                          setOpenAppMenu(null)
                                          hideSideBarMobile()
                                      },
                                      overlay: (
                                          <LemonButton
                                              status="stealth"
                                              onClick={() => openAppSourceEditor(id, pluginId)}
                                              fullWidth
                                          >
                                              Edit source code
                                          </LemonButton>
                                      ),
                                  },
                              }
                            : undefined
                    }
                />
            ))}
            {appSourceEditor ? (
                <PluginSource
                    pluginConfigId={appSourceEditor.id}
                    pluginId={appSourceEditor.pluginId}
                    visible={!!appSourceEditor}
                    close={() => closeAppSourceEditor()}
                    placement="right"
                />
            ) : null}
        </>
    )
}
