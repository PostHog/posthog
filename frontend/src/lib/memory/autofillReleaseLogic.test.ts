import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { autofillReleaseLogic } from './autofillReleaseLogic'

const SINK_SELECTOR = '#autofill-release-sink'

describe('autofillReleaseLogic', () => {
    let logic: ReturnType<typeof autofillReleaseLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = autofillReleaseLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('mounts a sink input and removes it on unmount', () => {
        expect(document.querySelectorAll(SINK_SELECTOR)).toHaveLength(1)
        logic.unmount()
        expect(document.querySelector(SINK_SELECTOR)).toBeNull()
    })

    it('evicts a stale sink left by a previous instance instead of duplicating it', () => {
        logic.unmount()
        const orphan = document.createElement('input')
        orphan.id = 'autofill-release-sink'
        document.body.appendChild(orphan)

        logic.mount()

        expect(document.querySelectorAll(SINK_SELECTOR)).toHaveLength(1)
    })

    it.each([
        { change: 'a different pathname', navigate: (): void => router.actions.push('/dashboard'), shouldFocus: true },
        {
            change: 'a query-only change',
            navigate: (): void => router.actions.push('/insights', { search: 'foo' }),
            shouldFocus: false,
        },
    ])('focuses the sink on $change: $shouldFocus', async ({ navigate, shouldFocus }) => {
        await expectLogic(logic, () => router.actions.push('/insights')).toDispatchActions(['locationChanged'])

        const sink = document.querySelector(SINK_SELECTOR) as HTMLInputElement
        const focusSpy = jest.spyOn(sink, 'focus')

        await expectLogic(logic, () => navigate()).toDispatchActions(['locationChanged'])

        expect(focusSpy).toHaveBeenCalledTimes(shouldFocus ? 1 : 0)
    })

    it('completes the scene change and reports the error if focusing the sink throws', async () => {
        await expectLogic(logic, () => router.actions.push('/insights')).toDispatchActions(['locationChanged'])

        const sink = document.querySelector(SINK_SELECTOR) as HTMLInputElement
        // a downstream blur handler on an unmounting form can throw when focus() moves off it
        const error = new TypeError('y is not a function')
        jest.spyOn(sink, 'focus').mockImplementation(() => {
            throw error
        })

        await expectLogic(logic, () => router.actions.push('/dashboard')).toDispatchActions(['locationChanged'])

        expect(router.values.location.pathname).toContain('/dashboard')
        // the failure is swallowed for navigation, but must still reach error tracking
        expect(posthog.captureException).toHaveBeenCalledWith(error, expect.any(Object))
    })
})
