import { useValues } from 'kea'
import { useLayoutEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { ToastProvider, toast } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { setQuillToasts } from 'lib/lemon-ui/LemonToast/quillToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function AppToaster(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    // Reads the window rather than todayShellLogic, which would mount the shell on pages that have none.
    // `md` is the shell's phone width, TODAY_PHONE_MAX_WIDTH.
    const { isWindowLessThan } = useWindowSize()
    const quill = !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]

    useLayoutEffect(() => {
        setQuillToasts(quill ? toast : null)
        return () => setQuillToasts(null)
    }, [quill])

    if (quill) {
        return (
            // The phone layout's tab bar holds the bottom of the screen.
            <ToastProvider limit={5} placement={isWindowLessThan('md') ? 'top-center' : 'bottom-right'}>
                {null}
            </ToastProvider>
        )
    }

    return (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )
}
