import { Tooltip } from '@base-ui/react/tooltip'
import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useLayoutEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { PostHogProvider } from '@posthog/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Auth } from 'scenes/authentication/auth/Auth'
import { authLogic } from 'scenes/authentication/auth/authLogic'
import { mountSupportRouter } from 'scenes/mountSupportRouter'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { authPrototypeLogic } from './authPrototypeLogic'

export function AuthPrototype(): JSX.Element {
    useMountedLogic(authLogic)
    useMountedLogic(authPrototypeLogic)
    useMountedLogic(preflightLogic)
    useMountedLogic(userLogic)

    const { preflight, preflightLoading } = useValues(preflightLogic)
    const { loadPreflight } = useActions(preflightLogic)
    const { user, userLoading } = useValues(userLogic)
    const canRenderAuth = !preflightLoading && !!preflight && !userLoading && !user

    useEffect(() => {
        if (canRenderAuth) {
            return mountSupportRouter().unmount
        }
    }, [canRenderAuth])
    useLayoutEffect(() => {
        performance.mark('auth-prototype:rendered')
    }, [])

    if (user || userLoading || preflightLoading) {
        return <div role="status">Loading login...</div>
    }

    if (!preflight) {
        return (
            <div role="alert">
                Login could not load. <LemonButton onClick={loadPreflight}>Try again</LemonButton>
            </div>
        )
    }

    return (
        <PostHogProvider client={posthog}>
            <Tooltip.Provider delay={500} closeDelay={0} timeout={400}>
                <Auth />
                <ToastContainer
                    autoClose={6000}
                    transition={Slide}
                    closeButton={<ToastCloseButton />}
                    position="bottom-right"
                    theme="light"
                />
            </Tooltip.Provider>
        </PostHogProvider>
    )
}
