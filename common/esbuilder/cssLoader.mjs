/**
 * The app stylesheet is attached at runtime instead of as a parser-blocking `<link>` in `<head>`,
 * so a slow CSS fetch does not hold up the boot scripts and the CSSOM keeps a single copy.
 *
 * That trade-off gives up the recovery a parser-inserted link gets for free, and the page has
 * nothing to fall back on: the critical CSS in index.html only covers the pre-React shell, so an
 * app that renders without this stylesheet paints raw markup at natural size. The failure is also
 * silent, because a `<link>` that fails or hangs raises no JavaScript error.
 *
 * This loader therefore treats the stylesheet as something that can fail. Each attempt has its own
 * timeout, because a stalled request fires no `error` event. `load` counts as success only when the
 * sheet applied, because a response that is not CSS fires `load` and leaves `link.sheet` null. A
 * failed attempt starts the next URL in the ladder: a stale CDN can refuse the hashed file but
 * serve the hashless copy, and a fresh query defeats a poisoned cache entry or a hung connection.
 * Each failure also sends an `$exception` beacon by hand, because posthog-js is not loaded this
 * early, the same way RootErrorBoundary reports boot failures.
 *
 * `window.ESBUILD_CSS_READY` resolves `true` once a stylesheet applies, and `false` once every
 * attempt has failed. The app entry waits on it before its first render (frontend/src/index.tsx).
 */

export const CSS_READY_GLOBAL = 'ESBUILD_CSS_READY'

/** How long one stylesheet request may hang before the loader gives up on it and tries the next. */
export const CSS_ATTEMPT_TIMEOUT_MS = 10000

export const STYLESHEET_ERROR_TYPE = 'StylesheetLoadError'

/**
 * Inline loader script. `cssFile` is the hashed stylesheet and `cssFileFallback` the hashless copy
 * with a build-id query. Dev builds pass the same path for both, and then the ladder is the file
 * plus its cache-busting retry.
 */
export function cssLoaderScript(cssFile, cssFileFallback) {
    const paths = cssFileFallback && cssFileFallback !== cssFile ? [cssFile, cssFileFallback] : [cssFile]
    return `
        (function () {
            var paths = ${JSON.stringify(paths)};
            var lastPath = paths[paths.length - 1];
            paths.push(lastPath + (lastPath.indexOf('?') === -1 ? '?' : '&') + 'retry=' + Date.now());

            var resolveReady;
            window.${CSS_READY_GLOBAL} = new Promise(function (resolve) { resolveReady = resolve; });
            var isReady = false;
            function settle(applied) {
                if (isReady) { return; }
                isReady = true;
                resolveReady(applied);
            }

            function report(reason, href, attempt) {
                console.error('[PostHog] App stylesheet ' + reason + ': ' + href);
                try {
                    var apiKey = window.JS_POSTHOG_API_KEY;
                    if (!apiKey) { return; }
                    var host = window.JS_POSTHOG_HOST || window.location.origin;
                    var distinctId;
                    try {
                        distinctId = JSON.parse(window.localStorage.getItem('ph_' + apiKey + '_posthog') || '{}').distinct_id;
                    } catch (e) {
                        // storage unavailable or corrupt, so report anonymously
                    }
                    var payload = JSON.stringify({
                        api_key: apiKey,
                        event: '$exception',
                        distinct_id: distinctId || ('stylesheet-failure-' + Date.now()),
                        properties: {
                            $process_person_profile: false,
                            // Origin only. This loader also runs on exporter.html, where the path
                            // carries the share token (/shared/<token>, /interview/<token>), and it
                            // runs before the exporter can redact it. stylesheet_href already says
                            // which build and which page type failed.
                            $current_url: window.location.origin,
                            $exception_level: attempt === paths.length ? 'fatal' : 'error',
                            $exception_list: [{
                                type: ${JSON.stringify(STYLESHEET_ERROR_TYPE)},
                                value: 'App stylesheet ' + reason,
                                mechanism: { handled: true, synthetic: true }
                            }],
                            stylesheet_href: href,
                            stylesheet_attempt: attempt,
                            stylesheet_attempts: paths.length
                        }
                    });
                    // A string body goes out as text/plain: CORS-safelisted and accepted by capture.
                    var url = host + '/e/';
                    if (!(typeof navigator.sendBeacon === 'function' && navigator.sendBeacon(url, payload))) {
                        fetch(url, { method: 'POST', body: payload, keepalive: true }).catch(function () {});
                    }
                } catch (e) {
                    // reporting a failure must never make the failure worse
                }
            }

            function attempt(index) {
                var href = (window.JS_URL || '') + '/static/' + paths[index];
                var link = document.createElement("link");
                link.rel = "stylesheet";
                link.crossOrigin = "anonymous";
                link.href = href;
                var isDone = false;
                var timer = setTimeout(function () { fail('stalled'); }, ${CSS_ATTEMPT_TIMEOUT_MS});
                function fail(reason) {
                    if (isDone) { return; }
                    isDone = true;
                    clearTimeout(timer);
                    report(reason, href, index + 1);
                    if (index + 1 < paths.length) {
                        attempt(index + 1);
                    } else {
                        settle(false);
                    }
                }
                link.addEventListener("load", function () {
                    if (!link.sheet) { fail('loaded but did not apply'); return; }
                    isDone = true;
                    clearTimeout(timer);
                    // A link left behind by an earlier timeout can still land and style the page,
                    // so a late load counts too.
                    settle(true);
                });
                link.addEventListener("error", function () { fail('failed to load'); });
                document.head.appendChild(link);
            }

            attempt(0);
        })();
    `
}

export const CSS_LOAD_GLOBAL = 'ESBUILD_LOAD_CSS'

/**
 * Inline loader for the stable build's split stylesheets (see frontend/bin/stableCss.mjs).
 *
 * The eager layers load in order, and `window.ESBUILD_CSS_READY` resolves once all of them apply.
 * `window.ESBUILD_LOAD_CSS(urls)` loads the stylesheets a lazy chunk waits on before it runs.
 *
 * When a stable stylesheet fails or stalls, the loader runs `cssLoaderScript` for the full
 * stylesheet, which holds every rule, with its whole retry and reporting ladder. A failure in the
 * stable build therefore ends up where the default build starts, never with an unstyled page.
 */
export function stableCssLoaderScript(eagerFiles, fullCssFile, fullCssFileFallback) {
    return `
        (function () {
            var fullStylesheet = null;
            function loadFullStylesheet() {
                if (!fullStylesheet) {
                    ${cssLoaderScript(fullCssFile, fullCssFileFallback)}
                    fullStylesheet = window.${CSS_READY_GLOBAL};
                }
                return fullStylesheet;
            }

            function loadStylesheet(href) {
                return new Promise(function (resolve) {
                    var link = document.createElement("link");
                    link.rel = "stylesheet";
                    link.crossOrigin = "anonymous";
                    link.href = href;
                    var timer = setTimeout(function () { resolve(false); }, ${CSS_ATTEMPT_TIMEOUT_MS});
                    link.addEventListener("load", function () { clearTimeout(timer); resolve(!!link.sheet); });
                    link.addEventListener("error", function () { clearTimeout(timer); resolve(false); });
                    document.head.appendChild(link);
                });
            }

            var requested = {};
            window.${CSS_LOAD_GLOBAL} = function (urls) {
                return Promise.all(urls.map(function (url) {
                    if (!requested[url]) {
                        requested[url] = loadStylesheet(url).then(function (applied) {
                            if (applied) { return true; }
                            console.error('[PostHog] Stylesheet did not apply, loading the full stylesheet: ' + url);
                            return loadFullStylesheet();
                        });
                    }
                    return requested[url];
                })).then(function (results) {
                    return results.every(Boolean);
                });
            };

            var eager = ${JSON.stringify(eagerFiles)}.map(function (file) {
                return (window.JS_URL || '') + '/static/' + file;
            });
            window.${CSS_READY_GLOBAL} = window.${CSS_LOAD_GLOBAL}(eager);
        })();
    `
}
