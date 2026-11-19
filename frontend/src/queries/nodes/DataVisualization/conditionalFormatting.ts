import posthog from 'posthog-js'

import type { execHog } from 'lib/hog'
import { lightenDarkenColor } from 'lib/utils/colors'

import { ConditionalFormattingRule } from '~/queries/schema/schema-general'

import { convertTableValue } from './dataVisualizationLogic'
import { ColumnScalar } from './types'

const invalidFormattingRules = new WeakSet<ConditionalFormattingRule>()

function reportInvalidFormattingRule(rule: ConditionalFormattingRule, captureExceptions: boolean): void {
    if (invalidFormattingRules.has(rule)) {
        return
    }
    invalidFormattingRules.add(rule)
    if (captureExceptions) {
        posthog.captureException(new Error('Invalid hog bytecode for conditional formatting'))
    }
}

export function conditionalFormattingColor(
    rules: ConditionalFormattingRule[],
    execute: typeof execHog | undefined,
    columnName: string,
    columnType: ColumnScalar,
    value: unknown,
    isDarkModeOn: boolean,
    captureExceptions = true
): string | undefined {
    if (!execute) {
        return undefined
    }
    const conditionalFormattingMatches = rules
        .filter((n) => n.columnName === columnName)
        .filter((n) => {
            if (invalidFormattingRules.has(n)) {
                return false
            }
            const isValidHog = !!n.bytecode && n.bytecode.length > 0 && n.bytecode[0] === '_H'
            if (!isValidHog) {
                reportInvalidFormattingRule(n, captureExceptions)
            }

            return isValidHog
        })
        .map((n) => {
            try {
                const result = execute(n.bytecode, {
                    globals: {
                        value: typeof value === 'string' ? convertTableValue(value, columnType) : value,
                        input: convertTableValue(n.input, columnType),
                    },
                    functions: {},
                    maxAsyncSteps: 0,
                    timeout: 5,
                })
                if (result.error) {
                    throw result.error
                }
                return { rule: n, result: result.result }
            } catch {
                reportInvalidFormattingRule(n, captureExceptions)
                return { rule: n, result: false }
            }
        })
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
