import { act, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ChartLoadingState, SLOW_LOAD_THRESHOLD_SECONDS } from './ChartLoadingState'

describe('ChartLoadingState', () => {
    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('explains a long load with elapsed time and a query debugger link', () => {
        render(<ChartLoadingState height={100} query={{ kind: 'ExperimentQuery' }} />)

        expect(screen.getByText('Loading results…')).toBeTruthy()

        act(() => {
            jest.advanceTimersByTime(SLOW_LOAD_THRESHOLD_SECONDS * 1000)
        })

        expect(screen.getByText(`Still loading results (0:${SLOW_LOAD_THRESHOLD_SECONDS})`)).toBeTruthy()
        expect(screen.getByText('Open in query debugger')).toBeTruthy()
    })
})
