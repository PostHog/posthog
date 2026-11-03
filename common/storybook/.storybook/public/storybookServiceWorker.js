/* eslint-disable */
// Storybook registers this worker instead of mockServiceWorker.js, which stays as `msw init` generates it.
//
// The msw worker sends every request of a story to the page, and the page answers each one. A story
// loads hundreds of JS chunks, stylesheets and fonts, so this message round trip was a large part of
// the main-thread work while a story loads. This listener runs before the msw listener and stops the
// event for static assets. The browser then fetches them from the network, and msw never sees them.
//
// Keep the pattern in sync with STATIC_ASSET_URL in frontend/src/mocks/browser.tsx.
const STATIC_ASSET_URL =
    /^https?:\/\/[^/]+\/(?!api\/)(?:(?:assets|static|sb-[\w-]+|@fs|@id|@vite|node_modules)\/.*|[^?#]*\.(?:m?js|jsx|tsx?|css|scss|less|woff2?|ttf|otf|png|jpe?g|gif|svg|webp|ico|map|wasm))$/

self.addEventListener('fetch', (event) => {
    const url = event.request.url.split(/[?#]/)[0]
    if (event.request.method === 'GET' && STATIC_ASSET_URL.test(url)) {
        event.stopImmediatePropagation()
    }
})

importScripts('./mockServiceWorker.js')
