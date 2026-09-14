import * as React from 'react'

import { CodeLoopLink, loopDeepLink } from './CodeLoopLink'

jest.mock('react', () => ({
    ...jest.requireActual('react'),
    useEffect: jest.fn(),
}))

describe('CodeLoopLink', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    it('encodes the loop id into the desktop deep link', () => {
        expect(loopDeepLink('loop/1')).toBe('posthog-code://loop/loop%2F1')
    })

    it('fires the deep link redirect for the rendered loop', () => {
        CodeLoopLink({ loopId: 'loop-1' })

        expect(React.useEffect).toHaveBeenCalledWith(expect.any(Function), ['posthog-code://loop/loop-1'])
    })
})
