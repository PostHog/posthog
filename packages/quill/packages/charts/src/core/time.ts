/** Monotonic millisecond timestamp for the chart animations (hover fade, count-up).
 *
 *  Prefers `performance.now()` — sub-millisecond and monotonic — and falls back to `Date.now()`
 *  where the global `performance` is absent. It is guaranteed in browsers, but not in every JS host
 *  the library runs under: jsdom test workers in particular don't always expose it, and a bare
 *  `performance.now()` there throws a `ReferenceError` mid-render that escapes into React's commit
 *  phase and trips the chart's error boundary. Reading it through `typeof` keeps the access safe
 *  even when the identifier is wholly undeclared.
 */
export function monotonicNow(): number {
    return typeof performance !== 'undefined' && typeof performance.now === 'function'
        ? performance.now()
        : Date.now()
}
