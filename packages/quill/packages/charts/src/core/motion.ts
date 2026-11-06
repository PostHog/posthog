/** True when the OS asks for reduced motion, so animations can snap to their end state instead of easing.
 *
 *  Read through `typeof` guards because `window`/`matchMedia` are absent in the jsdom test workers and
 *  other non-browser hosts the library runs under — a bare access would throw mid-render and trip the
 *  chart's error boundary. Missing support reads as "no preference", so animations run as before.
 */
export function prefersReducedMotion(): boolean {
    return (
        typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
    )
}
