import { actions, kea, key, path, props, reducers } from 'kea'

import type { lemonBannerLogicType } from './lemonBannerLogicType'

export type LemonBannerLogicProps = {
    /** The key to be used for persisting the fact this modal is dismissed */
    dismissKey: string
}

export const lemonBannerLogic = kea<lemonBannerLogicType>([
    path((key) => ['components', 'lemon-banner', 'lemonBannerLogic', key]),
    key(({ dismissKey }) => dismissKey),
    props({} as LemonBannerLogicProps),
    actions({
        dismiss: true,
        resetDismissKey: true,
    }),
    reducers({
        isDismissed: [
            false,
            { persist: true },
            {
                dismiss: () => true,
                resetDismissKey: () => false,
            },
        ],
    }),
])
