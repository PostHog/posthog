import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

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
        expect(document.querySelector(SINK_SELECTOR)).not.toBeNull()
        logic.unmount()
        expect(document.querySelector(SINK_SELECTOR)).toBeNull()
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
})
