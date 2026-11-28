import { useValues } from 'kea'
import { Suspense } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { FEATURE_FLAGS } from 'lib/constants'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

// Quill stays off the shell's eager path, so its toaster loads only behind the flag.
const QuillToaster = lazyWithRetry(() => import('./QuillToaster'))

function ToastifyToaster(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
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

export function AppToaster(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
        return (
            // lemonToast falls back to react-toastify until quill's viewport mounts, so the fallback shows those.
            <Suspense fallback={<ToastifyToaster />}>
                <QuillToaster />
            </Suspense>
        )
    }
    return <ToastifyToaster />
}
