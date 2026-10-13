import { createDevtoolsPanel } from './extensionBrowser'

// The panel shows the popup page, which reads the inspected tab when it runs in DevTools.
createDevtoolsPanel('PostHog', 'icons/favicon-32x32.png', 'popup.html')
