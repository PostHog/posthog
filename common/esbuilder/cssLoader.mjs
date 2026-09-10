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
 * sheet applied, because a response that is not CSS fires `load` too and leaves an empty sheet. A
 * failed attempt starts the next URL in the ladder: a stale CDN can refuse the hashed file but
 * serve the hashless copy, and a fresh query defeats a poisoned cache entry or a hung connection.
 * The last rung asks the app origin for the same file, because every rung before it resolves
 * against `JS_URL`, and one fault on the way to that host defeats all of them together.
 *
 * Each failure also sends an `$exception` beacon by hand, because posthog-js is not loaded this
 * early, the same way RootErrorBoundary reports boot failures. A `<link>` exposes neither the
 * response status nor the content type, so the beacon carries a short probe of the same URL: a
 * proxy interstitial, a MIME rewrite and a blocked host all look the same without it.
 *
 * `window.ESBUILD_CSS_READY` resolves `true` once a stylesheet applies, and `false` once every
 * attempt has failed. The app entry waits on it before its first render (frontend/src/index.tsx).
 */

export const CSS_READY_GLOBAL = 'ESBUILD_CSS_READY'

/** How long one stylesheet request may hang before the loader gives up on it and tries the next. */
export const CSS_ATTEMPT_TIMEOUT_MS = 10000

/** How long the diagnostic probe of a failed URL may hang before the beacon goes out without it. */
export const CSS_PROBE_TIMEOUT_MS = 3000

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

            var apiKey = window.JS_POSTHOG_API_KEY;
            var staticHost = window.JS_URL || '';
            var hrefs = [];
            for (var i = 0; i < paths.length; i++) {
                hrefs.push(staticHost + '/static/' + paths[i]);
            }
            // Dev and preview stacks point JS_URL at the app origin itself, and one that names the
            // default port reads as a different string for the same origin. Compare the resolved
            // origins, so the rung below is added only when there is another host to escape to.
            var isRemoteHost = false;
            if (staticHost) {
                try {
                    isRemoteHost = new URL(staticHost, window.location.href).origin !== window.location.origin;
                } catch (e) {
                    // A host string the browser cannot parse is no reason to give up the rung.
                    isRemoteHost = true;
                }
            }
            // The app origin serves the same files, so this rung survives a fault that reaches
            // every rung above: an interstitial in front of the static host, a MIME rewrite, or a
            // client that cannot reach that host at all.
            if (isRemoteHost) {
                hrefs.push('/static/' + paths[0]);
            }

            var resolveReady;
            window.${CSS_READY_GLOBAL} = new Promise(function (resolve) { resolveReady = resolve; });
            var isReady = false;
            function settle(applied) {
                if (isReady) { return; }
                isReady = true;
                resolveReady(applied);
            }

            // A link element reports neither the status nor the content type of its response, so ask for
            // the same URL again. The browser answers a cached response without a second request.
            function probe(href, done) {
                var isSettled = false;
                var controller = typeof AbortController === 'function' ? new AbortController() : null;
                function finish(diagnostics) {
                    if (isSettled) { return; }
                    isSettled = true;
                    clearTimeout(timer);
                    done(diagnostics);
                }
                var timer = setTimeout(function () {
                    if (controller) { controller.abort(); }
                    finish({ stylesheet_probe: 'stalled' });
                }, ${CSS_PROBE_TIMEOUT_MS});
                try {
                    fetch(href, { credentials: 'omit', signal: controller ? controller.signal : undefined })
                        .then(function (response) {
                            finish({
                                stylesheet_probe: 'answered',
                                stylesheet_status: response.status,
                                stylesheet_content_type: response.headers.get('content-type')
                            });
                        })
                        .catch(function () { finish({ stylesheet_probe: 'unreachable' }); });
                } catch (e) {
                    finish({ stylesheet_probe: 'unreachable' });
                }
            }

            function report(reason, href, attempt, diagnostics) {
                try {
                    var host = window.JS_POSTHOG_HOST || window.location.origin;
                    var distinctId;
                    try {
                        distinctId = JSON.parse(window.localStorage.getItem('ph_' + apiKey + '_posthog') || '{}').distinct_id;
                    } catch (e) {
                        // storage unavailable or corrupt, so report anonymously
                    }
                    var properties = {
                        $process_person_profile: false,
                        // Origin only. This loader also runs on exporter.html, where the path
                        // carries the share token (/shared/<token>, /interview/<token>), and it
                        // runs before the exporter can redact it. stylesheet_href already says
                        // which build and which page type failed.
                        $current_url: window.location.origin,
                        $exception_level: attempt === hrefs.length ? 'fatal' : 'error',
                        $exception_list: [{
                            type: ${JSON.stringify(STYLESHEET_ERROR_TYPE)},
                            value: 'App stylesheet ' + reason,
                            mechanism: { handled: true, synthetic: true }
                        }],
                        stylesheet_href: href,
                        stylesheet_attempt: attempt,
                        stylesheet_attempts: hrefs.length
                    };
                    for (var key in diagnostics) {
                        properties[key] = diagnostics[key];
                    }
                    var payload = JSON.stringify({
                        api_key: apiKey,
                        event: '$exception',
                        distinct_id: distinctId || ('stylesheet-failure-' + Date.now()),
                        properties: properties
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

            // A response that is not CSS fires a load event all the same. Some browsers leave
            // link.sheet null; Chromium builds the sheet and its MIME check leaves it empty. The
            // app stylesheet always has rules, so an empty sheet is an interstitial or a rewritten
            // content type, never the stylesheet.
            function didApply(link) {
                if (!link.sheet) { return false; }
                try {
                    return link.sheet.cssRules.length > 0;
                } catch (e) {
                    // A sheet the page may not read is still a sheet the browser applied.
                    return true;
                }
            }

            function attempt(index) {
                var href = hrefs[index];
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
                    // A link that an earlier timeout abandoned can still land and style the page.
                    // The ladder then has the stylesheet it asked for, so a later failure must not
                    // send a beacon or start another rung. A fatal beacon from a styled page also
                    // makes the fatal count read worse than the boot really was.
                    if (isReady) { return; }
                    console.error('[PostHog] App stylesheet ' + reason + ': ' + href);
                    // The probe only enriches the beacon, so it is worth a request only when
                    // there is a beacon to send. The ladder does not wait for either.
                    if (apiKey) {
                        probe(href, function (diagnostics) { report(reason, href, index + 1, diagnostics); });
                    }
                    if (index + 1 < hrefs.length) {
                        attempt(index + 1);
                    } else {
                        settle(false);
                    }
                }
                link.addEventListener("load", function () {
                    if (!didApply(link)) { fail('loaded but did not apply'); return; }
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
