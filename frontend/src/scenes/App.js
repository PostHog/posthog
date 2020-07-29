import 'react-toastify/dist/ReactToastify.css'
import 'react-datepicker/dist/react-datepicker.css'
import { hot } from 'react-hot-loader/root'

import React, { useState, useEffect, lazy, Suspense } from 'react'
import { useValues } from 'kea'
import { Layout, Spin } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { Sidebar } from '~/layout/Sidebar'
import { TopContent } from '~/layout/TopContent'
import { SendEventsOverlay } from '~/layout/SendEventsOverlay'
const OnboardingWizard = lazy(() => import('~/scenes/onboarding/onboardingWizard'))
import BillingToolbar from 'lib/components/BillingToolbar'

import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { router } from 'kea-router'

const darkerScenes = {
    dashboard: true,
    insights: true,
    funnel: true,
    editFunnel: true,
    paths: true,
}

const urlBackgroundMap = {
    '/dashboard': 'https://posthog.s3.eu-west-2.amazonaws.com/graphs.png',
    '/dashboard/1': 'https://posthog.s3.eu-west-2.amazonaws.com/graphs.png',
    '/events': 'https://posthog.s3.eu-west-2.amazonaws.com/preview-actions.png',
    '/sessions': 'https://posthog.s3.eu-west-2.amazonaws.com/preview-actions.png',
    '/actions': 'https://posthog.s3.eu-west-2.amazonaws.com/preview-actions.png',
    '/actions/live': 'https://posthog.s3.eu-west-2.amazonaws.com/preview-actions.png',
    '/insights': 'https://posthog.s3.eu-west-2.amazonaws.com/preview-action-trends.png',
    '/funnel': 'https://posthog.s3.eu-west-2.amazonaws.com/funnel.png',
    '/paths': 'https://posthog.s3.eu-west-2.amazonaws.com/paths.png',
}

function App() {
    const { user } = useValues(userLogic)
    const { scene, params, loadedScenes } = useValues(sceneLogic)
    const { location } = useValues(router)
    const [sidebarCollapsed, setSidebarCollapsed] = useState(typeof window !== 'undefined' && window.innerWidth <= 991)

    const [image, setImage] = useState(null)
    const Scene = loadedScenes[scene]?.component || (() => <SceneLoading />)

    useEffect(() => {
        setImage(urlBackgroundMap[location.pathname])
    }, [location.pathname])

    if (!user) {
        return null
    }

    if (!user.team.completed_snippet_onboarding) {
        return (
            <>
                <Suspense fallback={<Spin></Spin>}>
                    <OnboardingWizard user={user}></OnboardingWizard>
                </Suspense>
                <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
            </>
        )
    }

    return (
        <Layout className="bg-white">
            <Sidebar user={user} sidebarCollapsed={sidebarCollapsed} setSidebarCollapsed={setSidebarCollapsed} />
            <Layout
                className={`${darkerScenes[scene] ? 'bg-dashboard' : 'bg-white'}${
                    !sidebarCollapsed ? ' with-open-sidebar' : ''
                }`}
                style={{ minHeight: '100vh' }}
            >
                <div className="content py-3 layout-top-content">
                    <TopContent user={user} />
                </div>
                <Layout.Content className="pl-5 pr-5 pt-3" data-attr="layout-content">
                    {user.billing?.should_setup_billing && (
                        <BillingToolbar billingUrl={user.billing.subscription_url} />
                    )}
                    {!user.has_events && image ? (
                        <SendEventsOverlay image={image} user={user} />
                    ) : (
                        <Scene user={user} {...params} />
                    )}
                    <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
                </Layout.Content>
            </Layout>
        </Layout>
    )
}

export default hot(App)
