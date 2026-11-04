// Static assets skip msw, which otherwise round-trips every request through the page.
const STATIC_ASSET_URL =
    /^https?:\/\/[^/]+\/(?!api\/)(?:(?:assets|static|sb-[\w-]+|@fs|@id|@vite|node_modules)\/.*|[^?#]*\.(?:m?js|jsx|tsx?|css|scss|less|woff2?|ttf|otf|png|jpe?g|gif|svg|webp|ico|map|wasm))$/

self.addEventListener('fetch', (event) => {
    const url = event.request.url.split(/[?#]/)[0]
    if (event.request.method === 'GET' && STATIC_ASSET_URL.test(url)) {
        event.stopImmediatePropagation()
    }
})

importScripts('./mockServiceWorker.js')
