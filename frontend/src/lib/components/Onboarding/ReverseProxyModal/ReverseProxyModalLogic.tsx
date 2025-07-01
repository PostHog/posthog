import { actions, kea, path, reducers } from 'kea'

import type { reverseProxyModalLogicType } from './ReverseProxyModalLogicType'

export const reverseProxyModalLogic = kea<reverseProxyModalLogicType>([
    path(['lib', 'components', 'Onboarding', 'ReverseProxyModal', 'reverseProxyModalLogic']),
    actions({
        openReverseProxyModal: true,
        closeReverseProxyModal: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openReverseProxyModal: () => true,
                closeReverseProxyModal: () => false,
            },
        ],
    }),
])
