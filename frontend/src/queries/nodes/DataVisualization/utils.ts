import posthog from 'posthog-js'

import { execHog } from 'lib/hog'
import { lightenDarkenColor } from 'lib/utils'

import { ConditionalFormattingRule } from '~/queries/schema/schema-general'

import { convertTableValue } from './dataVisualizationLogic'
import { ColumnScalar } from './types'

/**
 * Evaluate conditional-formatting rules against a single cell value and return the first matching
 * rule, or undefined if none match. Shared by table cells (Table.tsx) and scalar tiles
 * (HogQLBoldNumber) so display behavior stays consistent across both surfaces.
 */
export function matchConditionalFormattingRule(
    rules: ConditionalFormattingRule[],
    sourceColumnName: string,
    cellValue: unknown,
    cellType: ColumnScalar
): ConditionalFormattingRule | undefined {
    for (const rule of rules) {
        if (rule.columnName !== sourceColumnName) {
            continue
        }
        const isValidHog = !!rule.bytecode && rule.bytecode.length > 0 && rule.bytecode[0] === '_H'
        if (!isValidHog) {
            posthog.captureException(new Error('Invalid hog bytecode for conditional formatting'), {
                formatRule: rule,
            })
            continue
        }
        const res = execHog(rule.bytecode, {
            globals: {
                value: cellValue,
                input: convertTableValue(rule.input, cellType),
            },
            functions: {},
            maxAsyncSteps: 0,
        })
        if (res.result) {
            return rule
        }
    }
    return undefined
}

/**
 * Resolve the background color a matched rule should paint, accounting for the rule's saved
 * `colorMode` versus the current UI theme. Used by both Table cell background tinting and
 * HogQLBoldNumber scalar tile tinting so theme adaptation is identical in both places.
 */
export function resolveConditionalFormattingBackground(rule: ConditionalFormattingRule, isDarkModeOn: boolean): string {
    const colorMode = rule.colorMode ?? 'light'
    if ((colorMode === 'dark' && isDarkModeOn) || (colorMode === 'light' && !isDarkModeOn)) {
        return rule.color
    }
    if (colorMode === 'dark' && !isDarkModeOn) {
        return lightenDarkenColor(rule.color, 30)
    }
    return lightenDarkenColor(rule.color, -30)
}
