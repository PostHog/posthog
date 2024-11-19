import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

/**
 * When SessionPlayerModal is present in the page you can call `openSessionPlayer` action to open the modal
 * and play a given session
 *
 * It assumes it is only placed in the page once and lives in the GlobalModals component as a result
 * Adding it to the page more than once will cause weird playback behaviour
 *
 */
export function PreviewingCustomCssModal(): JSX.Element | null {
    const { previewingCustomCss } = useValues(themeLogic)
    const { saveCustomCss } = useActions(themeLogic)

    return <LemonModal isOpen={true}>This is some contexyt</LemonModal>
}
