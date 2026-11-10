import '~/styles'

import { resetContext } from 'kea'
import { disposablesPlugin } from 'kea-disposables'
import { loadersPlugin } from 'kea-loaders'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { createRoot } from 'react-dom/client'

import { ExtensionPanel } from './components/panel/ExtensionPanel'
import { extensionAuthLogic } from './logics/panel/extensionAuthLogic'
import { extensionPanelLogic } from './logics/panel/extensionPanelLogic'

// The app's styles pick their colors from the body's theme attribute, which the panel takes from the browser.
const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)')
const applyBrowserTheme = (): void => document.body.setAttribute('theme', darkModeQuery.matches ? 'dark' : 'light')
applyBrowserTheme()
darkModeQuery.addEventListener('change', applyBrowserTheme)

resetContext({ plugins: [disposablesPlugin, loadersPlugin, subscriptionsPlugin] })
extensionPanelLogic.mount()
extensionAuthLogic.mount()

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExtensionPanel />)
}
