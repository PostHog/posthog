import { useLayoutEffect } from 'react'

import { ToastProvider, toast } from '@posthog/quill'

import { useWindowSize } from 'lib/hooks/useWindowSize'
import { setQuillToasts } from 'lib/lemon-ui/LemonToast/quillToast'

export default function QuillToaster(): JSX.Element {
    // Reads the window rather than todayShellLogic, which would mount the shell on pages that have none.
    // `md` is the shell's phone width, TODAY_PHONE_MAX_WIDTH.
    const { isWindowLessThan } = useWindowSize()

    useLayoutEffect(() => {
        setQuillToasts(toast)
        return () => setQuillToasts(null)
    }, [])

    return (
        // The phone layout's tab bar holds the bottom of the screen.
        <ToastProvider limit={5} placement={isWindowLessThan('md') ? 'top-center' : 'bottom-right'}>
            {null}
        </ToastProvider>
    )
}
