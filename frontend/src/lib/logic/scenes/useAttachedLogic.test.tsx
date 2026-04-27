import { cleanup, renderHook } from '@testing-library/react'
import { BuiltLogic, Logic, kea, path } from 'kea'

import { initKeaTests } from '~/test/init'

import { useAttachedLogic } from './useAttachedLogic'
import type { parentLogicType } from './useAttachedLogic.testType'

const parentLogic = kea<parentLogicType>([path(['lib', 'logic', 'scenes', 'useAttachedLogicTestParentLogic'])])

describe('useAttachedLogic', () => {
    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(() => {
        cleanup()
    })

    it('does not unmount a replaced attachment twice when the parent later unmounts', () => {
        const attachTo = parentLogic()
        const firstUnmount = jest.fn()
        const secondUnmount = jest.fn()
        const firstLogic = {
            pathString: 'test.logic.first',
            mount: jest.fn(() => firstUnmount),
        } as unknown as BuiltLogic<Logic>
        const secondLogic = {
            pathString: 'test.logic.second',
            mount: jest.fn(() => secondUnmount),
        } as unknown as BuiltLogic<Logic>

        const { rerender, unmount } = renderHook(({ logic }) => useAttachedLogic(logic, attachTo), {
            initialProps: { logic: firstLogic },
        })

        rerender({ logic: secondLogic })

        expect(firstLogic.mount).toHaveBeenCalledTimes(1)
        expect(firstUnmount).toHaveBeenCalledTimes(1)
        const attachments = (attachTo as any).attachments as Record<string, () => void>
        expect(attachments?.['test.logic.first']).toBeUndefined()
        expect(attachments?.['test.logic.second']).not.toBeUndefined()

        unmount()

        expect(firstUnmount).toHaveBeenCalledTimes(1)
        expect(secondLogic.mount).toHaveBeenCalledTimes(1)
        expect(secondUnmount).toHaveBeenCalledTimes(1)
        expect(attachments?.['test.logic.second']).toBeUndefined()
    })
})
