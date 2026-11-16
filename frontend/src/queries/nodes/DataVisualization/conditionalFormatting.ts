import posthog from 'posthog-js'

import type { execHog } from 'lib/hog'
import { lightenDarkenColor } from 'lib/utils/colors'

import { ConditionalFormattingRule } from '~/queries/schema/schema-general'

import { convertTableValue } from './dataVisualizationLogic'
import { ColumnScalar } from './types'

export function conditionalFormattingColor(
    rules: ConditionalFormattingRule[],
    execute: typeof execHog | undefined,
    columnName: string,
    columnType: ColumnScalar,
    value: unknown,
    isDarkModeOn: boolean
): string | undefined {
    if (!execute) {
        return undefined
    }
    const conditionalFormattingMatches = rules
        .filter((n) => n.columnName === columnName)
        .filter((n) => {
            const isValidHog = !!n.bytecode && n.bytecode.length > 0 && n.bytecode[0] === '_H'
            if (!isValidHog) {
                posthog.captureException(new Error('Invalid hog bytecode for conditional formatting'), {
                    formatRule: n,
                })
            }

            return isValidHog
        })
        .map((n) => ({
            rule: n,
            result: execute(n.bytecode, {
                globals: {
                    value: typeof value === 'string' ? convertTableValue(value, columnType) : value,
                    input: convertTableValue(n.input, columnType),
                },
                functions: {},
                maxAsyncSteps: 0,
            }).result,
        }))
        .find((n) => Boolean(n.result))

    if (!conditionalFormattingMatches) {
        return undefined
    }

    const ruleColor = conditionalFormattingMatches.rule.color
    const colorMode = conditionalFormattingMatches.rule.colorMode ?? 'light'

    // If the color mode matches the current theme, use the color as it was saved
    if ((colorMode === 'dark' && isDarkModeOn) || (colorMode === 'light' && !isDarkModeOn)) {
        return ruleColor
    }

    // If the color mode is dark, but we're in light mode - then lighten the color
    if (colorMode === 'dark' && !isDarkModeOn) {
        return lightenDarkenColor(ruleColor, 30)
    }

    // If the color mode is light, but we're in dark mode - then darken the color
    return lightenDarkenColor(ruleColor, -30)
}
