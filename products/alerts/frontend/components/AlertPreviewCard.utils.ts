import type { ReferenceLineLabelPosition } from '@posthog/quill-charts'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import type { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'

export interface AlertThresholdLine {
    value: number
    label: string
    labelPosition: ReferenceLineLabelPosition
}

export function thresholdReferenceLines(alertForm: AlertFormType): AlertThresholdLine[] {
    if (alertForm.detector_config) {
        return []
    }
    const configuration = alertForm.threshold?.configuration
    const bounds = configuration?.bounds
    const relativePercentage =
        alertForm.condition?.type !== AlertConditionType.ABSOLUTE_VALUE &&
        configuration?.type === InsightThresholdType.PERCENTAGE
    const displayValue = (value: number): number => (relativePercentage ? value * 100 : value)
    const lines: AlertThresholdLine[] = []
    if (bounds?.upper != null && !Number.isNaN(bounds.upper)) {
        const value = displayValue(bounds.upper)
        lines.push({
            value,
            label: `above ${humanFriendlyNumber(value)}`,
            labelPosition: 'end',
        })
    }
    if (bounds?.lower != null && !Number.isNaN(bounds.lower)) {
        const value = displayValue(bounds.lower)
        lines.push({
            value,
            label: `below ${humanFriendlyNumber(value)}`,
            labelPosition: 'start',
        })
    }
    return lines
}

export function shouldUseLogScale(values: number[], referenceLines: AlertThresholdLine[]): boolean {
    if (
        referenceLines.length === 0 ||
        values.some((value) => value < 0 || !Number.isFinite(value)) ||
        referenceLines.some((line) => line.value < 0)
    ) {
        return false
    }
    const positiveThresholds = referenceLines.map((line) => line.value).filter((value) => value > 0)
    if (positiveThresholds.length === 0) {
        return false
    }
    const largestValue = Math.max(...values, ...positiveThresholds)
    const smallestThreshold = Math.min(...positiveThresholds)
    return largestValue / smallestThreshold >= 1000
}
