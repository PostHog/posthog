import { resetContext } from 'kea'
import { createRoot } from 'react-dom/client'

import { TOOLBAR_EXTENSION_ID } from '~/toolbar/utils'

import { isContentMessage } from './contentBridge'
import { onContentCommand } from './extensionBrowser'
import { extensionContentLogic } from './extensionContentLogic'
import { ExtensionContentOverlay } from './ExtensionContentOverlay'

// The popup injects this script again when it can't reach it, so a second run in the same page must do nothing.
const INSTALLED_FLAG = '__posthogToolbarExtensionContent'

function install(): void {
    resetContext()
    extensionContentLogic.mount()

    const host = document.createElement('div')
    host.id = TOOLBAR_EXTENSION_ID
    // ph-no-capture keeps the page's own posthog-js from recording the overlay.
    host.className = 'ph-no-capture'
    // Absolute at the document origin, so element rects in page coordinates line up while the page scrolls.
    host.style.cssText =
        'position:absolute;top:0;left:0;width:0;height:0;overflow:visible;z-index:2147483647;pointer-events:none'
    const container = document.createElement('div')
    host.attachShadow({ mode: 'open' }).appendChild(container)
    document.documentElement.appendChild(host)
    createRoot(container).render(<ExtensionContentOverlay />)

    onContentCommand((message) => {
        if (!isContentMessage(message)) {
            return null
        }
        extensionContentLogic.actions.handleCommand(message.command)
        return extensionContentLogic.values.status
    })
}

const contentGlobal = globalThis as unknown as Record<string, boolean | undefined>
if (!contentGlobal[INSTALLED_FLAG]) {
    contentGlobal[INSTALLED_FLAG] = true
    install()
}
