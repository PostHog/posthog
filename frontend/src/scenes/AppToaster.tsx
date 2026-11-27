import { useValues } from 'kea'
import { useLayoutEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { ToastProvider, toast } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { setQuillToasts } from 'lib/lemon-ui/LemonToast/quillToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function AppToaster(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const quill = !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]

    useLayoutEffect(() => {
        setQuillToasts(quill ? toast : null)
        return () => setQuillToasts(null)
    }, [quill])

    if (quill) {
        return <ToastProvider>{null}</ToastProvider>
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
