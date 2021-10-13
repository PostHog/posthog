import React from 'react'
import { BindLogic, kea, useMountedLogic, useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { MainNavigation, TopNavigation, DemoWarnings } from '~/layout/navigation'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { CommandPalette } from 'lib/components/CommandPalette'
import { UpgradeModal } from './UpgradeModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from './PreflightCheck/logic'
import { BackTo } from 'lib/components/BackTo'
import { Papercups } from 'lib/components/Papercups'
import { appLogicType } from './AppType'
import { models } from '~/models'
import { FEATURE_FLAGS } from 'lib/constants'
import { CloudAnnouncement } from '~/layout/navigation/CloudAnnouncement'
import { teamLogic } from './teamLogic'
import { ProjectBasedLogicProps } from '../types'
import { actionsModel } from '../models/actionsModel'
import { annotationsModel } from '../models/annotationsModel'
import { cohortsModel } from '../models/cohortsModel'
import { dashboardsModel } from '../models/dashboardsModel'
import { eventDefinitionsModel } from '../models/eventDefinitionsModel'
import { personPropertiesModel } from '../models/personPropertiesModel'
import { propertyDefinitionsModel } from '../models/propertyDefinitionsModel'

export const appLogic = kea<appLogicType>({
    actions: {
        enableDelayedSpinner: true,
        ignoreFeatureFlags: true,
    },
    reducers: {
        showingDelayedSpinner: [false, { enableDelayedSpinner: () => true }],
        featureFlagsTimedOut: [false, { ignoreFeatureFlags: () => true }],
    },
    selectors: {
        showApp: [
            (s) => [
                userLogic.selectors.userLoading,
                userLogic.selectors.user,
                featureFlagLogic.selectors.receivedFeatureFlags,
                s.featureFlagsTimedOut,
                preflightLogic.selectors.preflightLoading,
                preflightLogic.selectors.preflight,
            ],
            (userLoading, user, receivedFeatureFlags, featureFlagsTimedOut, preflightLoading, preflight) => {
                return (
                    (!userLoading || user) &&
                    (receivedFeatureFlags || featureFlagsTimedOut) &&
                    (!preflightLoading || preflight)
                )
            },
        ],
    },
    events: ({ actions, cache }) => ({
        afterMount: () => {
            cache.spinnerTimeout = window.setTimeout(() => actions.enableDelayedSpinner(), 1000)
            cache.featureFlagTimeout = window.setTimeout(() => actions.ignoreFeatureFlags(), 3000)
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.spinnerTimeout)
            window.clearTimeout(cache.featureFlagTimeout)
        },
    }),
})

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner } = useValues(appLogic)
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)

    if (showApp) {
        const projectBasedLogicProps: ProjectBasedLogicProps = { teamId: currentTeamId }
        return (
            <BindLogic logic={actionsModel} props={projectBasedLogicProps}>
                <BindLogic logic={annotationsModel} props={projectBasedLogicProps}>
                    <BindLogic logic={cohortsModel} props={projectBasedLogicProps}>
                        <BindLogic logic={dashboardsModel} props={projectBasedLogicProps}>
                            <BindLogic logic={eventDefinitionsModel} props={projectBasedLogicProps}>
                                <BindLogic logic={personPropertiesModel} props={projectBasedLogicProps}>
                                    <BindLogic logic={propertyDefinitionsModel} props={projectBasedLogicProps}>
                                        {user && currentTeamId ? <Models teamId={currentTeamId} /> : null}
                                        <AppScene />
                                    </BindLogic>
                                </BindLogic>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        )
    }

    return showingDelayedSpinner ? <SceneLoading /> : null
}

/** Loads every logic in the "src/models" folder */
function Models({ teamId }: Required<ProjectBasedLogicProps>): null {
    useMountedLogic(models({ teamId }))
    return null
}

function AppScene(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { activeScene, params, loadedScenes, sceneConfig } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showingDelayedSpinner } = useValues(appLogic)

    const SceneComponent: (...args: any[]) => JSX.Element | null =
        (activeScene ? loadedScenes[activeScene]?.component : null) ||
        (() => (showingDelayedSpinner ? <SceneLoading /> : null))

    const essentialElements = (
        // Components that should always be mounted inside Layout
        <>
            {featureFlags[FEATURE_FLAGS.PAPERCUPS_ENABLED] && <Papercups />}
            <ToastContainer autoClose={8000} transition={Slide} position="top-right" />
        </>
    )

    if (!user) {
        return sceneConfig.onlyUnauthenticated || sceneConfig.allowUnauthenticated ? (
            <Layout style={{ minHeight: '100vh' }}>
                <SceneComponent {...params} />
                {essentialElements}
            </Layout>
        ) : null
    }

    if (sceneConfig.plain) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                {!sceneConfig.hideTopNav && <TopNavigation />}
                <SceneComponent user={user} {...params} />
                {essentialElements}
            </Layout>
        )
    }

    return (
        <>
            <Layout>
                <MainNavigation />
                <Layout className={`${sceneConfig.dark ? 'bg-mid' : ''}`} style={{ minHeight: '100vh' }}>
                    {!sceneConfig.hideTopNav && <TopNavigation />}
                    {activeScene ? (
                        <Layout.Content className="main-app-content" data-attr="layout-content">
                            {!sceneConfig.hideDemoWarnings && <DemoWarnings />}
                            {featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT] ? (
                                <CloudAnnouncement message={String(featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT])} />
                            ) : null}
                            <BillingAlerts />
                            <BackTo />
                            <SceneComponent user={user} {...params} />
                        </Layout.Content>
                    ) : null}
                </Layout>
                {essentialElements}
            </Layout>
            <UpgradeModal />
            <CommandPalette />
        </>
    )
}
