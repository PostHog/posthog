import { http, HttpResponse } from 'msw'

import { worker } from '~/mocks/browser'
import type { AppContext } from '~/types'

import { getStorybookAppContext } from '../../../common/storybook/.storybook/app-context'

// The entry of the mock app (vite.mock-app.config.mts). It must finish this setup before the app
// module runs, which a bundler only guarantees for code in this module, not for an export of it.

// A static host answers an unknown URL with the HTML shell, which the app cannot read as JSON. So
// an API request that no fixture covers gets a 404 here, after every other handler has passed on it.
const unmockedApiHandler = http.all('/api/*', ({ request }) => {
    const { pathname } = new URL(request.url)
    console.warn(`[mock app] No mock for ${request.method} ${pathname}`)
    return HttpResponse.json({ detail: 'The mock app has no fixture for this request.' }, { status: 404 })
})
worker.resetHandlers(...worker.listHandlers(), unmockedApiHandler)

window.POSTHOG_APP_CONTEXT = getStorybookAppContext() as AppContext

void worker
    .start({
        serviceWorker: { url: '/storybookServiceWorker.js' },
        quiet: true,
        onUnhandledRequest: 'bypass',
    })
    .then(() => import('~/index'))
