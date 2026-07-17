import type { BeforeSendFn } from 'posthog-js'

type FilterableEvent = { event?: string; properties?: Record<string, any> } | null

/**
 * kea-forms throws `new Error('Validation Failed')` from its async submit chain whenever a form
 * fails client-side field validation. With exception autocapture on, posthog-js files that
 * rejection as a handled `$exception` — but it's expected behavior (the user already sees the
 * inline field errors) and its stack has no app frames, so it can't be attributed to a form.
 * Drop it before it leaves the browser so every form benefits, generalizing the per-form guard
 * in `subscriptionLogic`. Exported for unit testing.
 */
export function dropKeaFormsValidationErrors<T extends FilterableEvent>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string; value?: string }>
    if (list.some((ex) => ex?.type === 'Error' && ex?.value === 'Validation Failed')) {
        return null
    }
    return event
}

/**
 * Always-on `$exception` noise filters wired into posthog-js at init for every bundle. Each drops
 * a class of expected-behavior exception that would otherwise clutter error tracking. Kept as a
 * shared list so filters that dynamically own the `before_send` slot (e.g. `selfReadOnlyModeLogic`)
 * can compose these in rather than clobber them.
 */
export const EXCEPTION_AUTOCAPTURE_NOISE_FILTERS: BeforeSendFn[] = [dropKeaFormsValidationErrors]
