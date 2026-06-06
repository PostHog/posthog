import { afterMount, beforeUnmount, connect, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import type { autofillReleaseLogicType } from './autofillReleaseLogicType'

const SINK_ID = 'autofill-release-sink'

/**
 * Workaround for a Chromium AutofillAgent retention bug.
 *
 * Blink's AutofillAgent keeps a strong (C++ Persistent) reference to the
 * last-focused form control, and does not release it when that element is
 * removed from the DOM. An `autoFocus`'d input inside a scene (e.g. the
 * saved-insights search box) therefore pins its entire detached subtree —
 * the whole results table, every row, cell and sparkline — across SPA
 * navigation. Forced GC cannot reclaim it. Across navigations this is a
 * large, steady source of detached-DOM growth.
 *
 * The agent only drops the reference when a *different* form control is
 * focused (a new autofill query). Blurring alone does not release it. So on
 * every scene change we momentarily focus a persistent off-screen sink
 * input, moving the agent's reference onto a node that never detaches. The
 * next scene's own `autoFocus` (if any) then takes the reference over from
 * the sink. We blur the sink immediately so it never holds visible focus.
 *
 * Sibling in spirit to `useCancelAnimationsOnUnmount`, which severs the
 * DocumentTimeline -> animation -> element retention on the same SPA
 * navigation boundary.
 *
 * Upstream Chromium bug: https://issues.chromium.org/issues/342247579
 * Delete this file once it is fixed.
 */
export const autofillReleaseLogic = kea<autofillReleaseLogicType>([
    path(['lib', 'memory', 'autofillReleaseLogic']),
    connect(() => ({
        actions: [router, ['locationChanged']],
    })),
    afterMount(({ cache }) => {
        const sink = document.createElement('input')
        sink.id = SINK_ID
        sink.type = 'text'
        sink.tabIndex = -1
        sink.setAttribute('aria-hidden', 'true')
        // off-screen rather than `display:none`/`sr-only` clip: the element
        // must stay focusable and "visible enough" for the autofill agent to
        // re-query it, which is what releases the previous element
        sink.style.position = 'fixed'
        sink.style.left = '-9999px'
        sink.style.top = '0'
        document.body.appendChild(sink)
        cache.sink = sink
        cache.lastPathname = router.values.location.pathname
    }),
    beforeUnmount(({ cache }) => {
        const sink = cache.sink as HTMLInputElement | undefined
        sink?.remove()
        cache.sink = undefined
    }),
    listeners(({ cache }) => ({
        locationChanged: ({ pathname }) => {
            // only release on an actual scene change. query/hash updates fire
            // locationChanged too (scenes sync filters to the URL), and
            // stealing focus on those would break a scene's own search box
            // mid-keystroke
            if (pathname === cache.lastPathname) {
                return
            }
            cache.lastPathname = pathname
            const sink = cache.sink as HTMLInputElement | undefined
            if (!sink) {
                return
            }
            sink.focus()
            sink.blur()
        },
    })),
])
