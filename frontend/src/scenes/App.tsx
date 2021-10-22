import React from 'react'
import { kea, useMountedLogic, useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { MainNavigation, TopNavigation, DemoWarnings } from '~/layout/navigation'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import { userLogic } from 'scenes/userLogic'
import { SceneComponent, sceneLogic } from 'scenes/sceneLogic'
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
    const { sceneConfig } = useValues(sceneLogic)

    if (showApp) {
        return (
            <>
                {user && currentTeamId ? <Models /> : null}
                {(!sceneConfig.projectBased || currentTeamId) && <AppScene />}
            </>
        )
    }

    return showingDelayedSpinner ? <SceneLoading /> : null
}

/** Loads every logic in the "src/models" folder */
function Models(): null {
    useMountedLogic(models)
    return null
}

function OneScene({
    Component,
    sceneId,
    params,
}: {
    Component: SceneComponent
    activeSceneId: string
    sceneId: string
    params: Record<string, any>
}): JSX.Element | null {
    return <Component sceneId={sceneId} {...params} />
}

const MemoizedScene = React.memo(OneScene, (_, nextProps) => nextProps.activeSceneId !== nextProps.sceneId)

function AppScene(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { activeScene, loadedScenes, sceneConfig, sceneHistory, activeSceneId } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const sceneComponent = sceneHistory.history.map(({ scene, params, sceneId }, index) => {
        const Component = loadedScenes[scene]?.component
        return (
            <React.Fragment key={sceneId}>
                {!!Component ? (
                    <div
                        style={{
                            width: '100%',
                            height: '100%',
                            display: sceneHistory.index === index ? 'block' : 'none',
                        }}
                    >
                        <MemoizedScene
                            Component={Component}
                            params={params}
                            sceneId={sceneId}
                            activeSceneId={activeSceneId || sceneId}
                        />
                    </div>
                ) : null}
            </React.Fragment>
        )
    })

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
                {sceneComponent}
                {essentialElements}
            </Layout>
        ) : null
    }

    if (sceneConfig.plain) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                {!sceneConfig.hideTopNav && <TopNavigation />}
                {sceneComponent}
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
                            {sceneComponent}
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
