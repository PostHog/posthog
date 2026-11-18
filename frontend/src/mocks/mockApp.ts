import { http, HttpResponse } from 'msw'

import { worker } from '~/mocks/browser'
import type { AppContext } from '~/types'

import { getStorybookAppContext } from '../../../common/storybook/.storybook/app-context'

// A bundler drops an entry's exports, so this entry runs its setup and then imports the app.

// A static host answers unknown URLs with the HTML shell, so unmocked API requests get a 404 here.
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
