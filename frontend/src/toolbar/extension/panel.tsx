import '~/styles'

import { resetContext } from 'kea'
import { loadersPlugin } from 'kea-loaders'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { createRoot } from 'react-dom/client'

import { extensionAuthLogic } from './extensionAuthLogic'
import { ExtensionPanel } from './ExtensionPanel'
import { extensionPanelLogic } from './extensionPanelLogic'

resetContext({ plugins: [loadersPlugin, subscriptionsPlugin] })
extensionPanelLogic.mount()
extensionAuthLogic.mount()

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExtensionPanel />)
}
