import '~/styles'
import '~/toolbar/shared/styles.scss'

import { resetContext } from 'kea'
import { disposablesPlugin } from 'kea-disposables'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'

import { TOOLBAR_EXTENSION_ID, TOOLBAR_ROOT_ATTRIBUTE } from '~/toolbar/shared/utils'

import { answerContentScriptPing } from './browser/extensionBrowser'
import { PageToolbarHost } from './components/page/pageToolbarHost'

const INSTALLED_FLAG = '__posthogToolbarExtensionContent'

function resetPageToolbarContext(): void {
    // The prefix keeps the settings the toolbar logics persist in the page's localStorage apart from the floating toolbar's.
    resetContext({
        plugins: [
            disposablesPlugin,
            localStoragePlugin({ prefix: 'posthogToolbarExtension' }),
            windowValuesPlugin({ window }),
            formsPlugin,
            loadersPlugin,
            subscriptionsPlugin,
            waitForPlugin,
        ],
    })
}

function install(): void {
    resetPageToolbarContext()
    const host = document.createElement('div')
    host.id = TOOLBAR_EXTENSION_ID
    host.setAttribute(TOOLBAR_ROOT_ATTRIBUTE, '')
    // ph-no-capture keeps the page's own posthog-js from recording the overlay.
    host.className = 'ph-no-capture'
    host.style.cssText =
        'position:absolute;top:0;left:0;width:100%;height:100%;overflow:visible;z-index:2147483647;pointer-events:none'
    const shadowRoot = host.attachShadow({ mode: 'open' })
    document.documentElement.appendChild(host)
    new PageToolbarHost(shadowRoot, resetPageToolbarContext).listen()
    answerContentScriptPing()
}

const contentGlobal = globalThis as unknown as Record<string, boolean | undefined>
if (!contentGlobal[INSTALLED_FLAG]) {
    contentGlobal[INSTALLED_FLAG] = true
    install()
}
