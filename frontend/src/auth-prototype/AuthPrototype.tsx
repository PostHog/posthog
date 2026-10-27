import { Tooltip } from '@base-ui/react/tooltip'
import { useMountedLogic } from 'kea'
import posthog from 'posthog-js'
import { useLayoutEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { PostHogProvider } from '@posthog/react'

import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Auth } from 'scenes/authentication/auth/Auth'
import { authLogic } from 'scenes/authentication/auth/authLogic'

import { authPrototypeLogic } from './authPrototypeLogic'

export function AuthPrototype(): JSX.Element {
    useMountedLogic(authLogic)
    useMountedLogic(authPrototypeLogic)

    useLayoutEffect(() => {
        performance.mark('auth-prototype:rendered')
    }, [])

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
