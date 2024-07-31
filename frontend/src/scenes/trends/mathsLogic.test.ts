import { FEATURE_FLAGS } from '~/lib/constants'
import { BaseMathType } from '~/types'

import { filterMathTypesUnderFeatureFlags, MathCategory, MathDefinition } from './mathsLogic'

describe('mathsLogic', () => {
    it('should filter out math types that are not enabled', () => {
        const mathDefinitions: Record<string, MathDefinition> = {
            test: { name: 'test', category: MathCategory.EventCount, shortName: 'test', description: 'test' },
            [BaseMathType.FirstTimeForUser]: {
                name: 'test',
                category: MathCategory.EventCount,
                shortName: 'test',
                description: 'test',
            },
        }

        expect(
            filterMathTypesUnderFeatureFlags(mathDefinitions, {
                [FEATURE_FLAGS.FIRST_TIME_FOR_USER_MATH]: true,
            })
        ).toEqual(mathDefinitions)

        const res = filterMathTypesUnderFeatureFlags(mathDefinitions, {
            [FEATURE_FLAGS.FIRST_TIME_FOR_USER_MATH]: false,
        })
        expect(res).not.toHaveProperty(BaseMathType.FirstTimeForUser)
        expect(res).toHaveProperty('test', mathDefinitions.test)
    })
})
