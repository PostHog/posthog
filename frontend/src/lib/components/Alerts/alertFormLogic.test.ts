import { AlertConditionType } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { canCheckOngoingInterval } from './alertFormLogic'

describe('alertFormLogic utils', () => {
    beforeEach(() => {
        initKeaTests(false)
    })

    describe('canCheckOngoingInterval', () => {
        it('returns true for absolute value alerts with upper threshold', () => {
            const alert = {
                condition: { type: AlertConditionType.ABSOLUTE_VALUE },
                threshold: {
                    configuration: {
                        bounds: { upper: 100 },
                    },
                },
            } as any

            expect(canCheckOngoingInterval(alert)).toBe(true)
        })

        it('returns true for relative increase alerts with upper threshold', () => {
            const alert = {
                condition: { type: AlertConditionType.RELATIVE_INCREASE },
                threshold: {
                    configuration: {
                        bounds: { upper: 50 },
                    },
                },
            } as any

            expect(canCheckOngoingInterval(alert)).toBe(true)
        })

        it('returns false when no upper threshold is set', () => {
            const alert = {
                condition: { type: AlertConditionType.ABSOLUTE_VALUE },
                threshold: {
                    configuration: {
                        bounds: { lower: 10 },
                    },
                },
            } as any

            expect(canCheckOngoingInterval(alert)).toBe(false)
        })

        it('returns false for other condition types', () => {
            const alert = {
                condition: { type: AlertConditionType.RELATIVE_DECREASE },
                threshold: {
                    configuration: {
                        bounds: { upper: 100 },
                    },
                },
            } as any

            expect(canCheckOngoingInterval(alert)).toBe(false)
        })

        it('handles undefined alert gracefully', () => {
            expect(canCheckOngoingInterval(undefined)).toBe(false)
        })

        it('handles malformed alert data gracefully', () => {
            const alert = {
                condition: { type: AlertConditionType.ABSOLUTE_VALUE },
                threshold: {
                    configuration: {
                        bounds: { upper: NaN },
                    },
                },
            } as any

            expect(canCheckOngoingInterval(alert)).toBe(false)
        })
    })
})
