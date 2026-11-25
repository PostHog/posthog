import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { CohortRealtimeReadinessApi } from '../generated/api.schemas'
import { CohortRealtimeStatus } from './CohortRealtimeStatus'

const needsAttention = (reason: CohortRealtimeReadinessApi['reason']): CohortRealtimeReadinessApi => ({
    state: 'needs_attention',
    ready_at: null,
    build: null,
    reason,
    history_limit_days: null,
})

describe('CohortRealtimeStatus', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['nothing is preparing it', null, true],
        ['it is too large to build', 'too_large_to_build' as const, false],
    ])('whether it offers to try again when %s', (_case, reason, offered) => {
        const onSwitch = jest.fn()
        render(
            <Provider>
                <CohortRealtimeStatus
                    realtime={needsAttention(reason)}
                    switchAction="turn_off"
                    switching={false}
                    onSwitch={onSwitch}
                />
            </Provider>
        )

        const retry = screen.queryByText('Try again')
        if (!offered) {
            expect(retry).not.toBeInTheDocument()
            return
        }
        fireEvent.click(retry as HTMLElement)
        expect(onSwitch).toHaveBeenCalledWith(true)
    })
})
