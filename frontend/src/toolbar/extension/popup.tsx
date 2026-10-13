import '~/styles'

import { resetContext } from 'kea'
import { loadersPlugin } from 'kea-loaders'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { createRoot } from 'react-dom/client'

import { ExtensionPopup } from './ExtensionPopup'
import { extensionPopupLogic } from './extensionPopupLogic'

resetContext({ plugins: [loadersPlugin, subscriptionsPlugin] })
extensionPopupLogic.mount()

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExtensionPopup />)
}
