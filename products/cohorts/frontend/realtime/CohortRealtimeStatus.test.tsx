import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { CohortRealtimeReadinessApi } from '../generated/api.schemas'
import { CohortRealtimeStatus } from './CohortRealtimeStatus'
import { dailyReasonSentence, unpreparableReasonSentence } from './realtimeReadiness'

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

    it.each([
        ['a daily cohort', 'daily' as const, 'action_criteria' as const, null, dailyReasonSentence],
        ['an off cohort', 'off' as const, 'unsupported_time_range' as const, null, unpreparableReasonSentence],
        [
            'an off cohort over the plan limit',
            'off' as const,
            'history_over_limit' as const,
            30,
            unpreparableReasonSentence,
        ],
    ])('shows why %s is unavailable without a hover', (_case, state, reason, historyLimitDays, sentenceFor) => {
        const realtime: CohortRealtimeReadinessApi = {
            ...needsAttention(reason),
            state,
            history_limit_days: historyLimitDays,
        }
        const sentence = sentenceFor(realtime)
        if (sentence === null) {
            throw new Error(`no reason sentence for ${state} ${reason}`)
        }
        render(
            <Provider>
                <CohortRealtimeStatus realtime={realtime} switchAction={null} switching={false} onSwitch={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText(sentence)).toBeInTheDocument()
    })
})
