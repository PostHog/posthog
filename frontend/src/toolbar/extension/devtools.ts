import { createDevtoolsPanel } from './extensionBrowser'

// The DevTools panel shows the side panel page, which reads the inspected tab when it runs in DevTools.
createDevtoolsPanel('PostHog', 'icons/favicon-32x32.png', 'panel.html')
