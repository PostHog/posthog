import { IconList } from '@posthog/icons'

import {
    EXCEPTION_STEP_INTERNAL_FIELDS,
    RawExceptionStep,
    getExceptionStepMalformedReason,
} from 'lib/components/Errors/exceptionStepsValidation'
import { ErrorEventProperties, ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { Dayjs, dayjs } from 'lib/dayjs'

import { PropertiesTable } from 'products/error_tracking/frontend/components/PropertiesTable'
import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { ItemCategory, ItemLoader, ItemRenderer, TimelineItem } from '..'
import { StandardizedPreview } from './base'

export interface ExceptionStepItem extends TimelineItem {
    payload: {
        runtime: ErrorTrackingRuntime
        type?: string
        message: string
        level?: string
        stepProperties?: Record<string, unknown>
        stepIndex?: number
    }
}

export const exceptionStepRenderer: ItemRenderer<ExceptionStepItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconList />,
    render: ({ item }): JSX.Element => {
        return <StandardizedPreview primaryText={item.payload.message} secondaryText={item.payload.type} />
    },
    renderExpanded: ({ item }): JSX.Element => {
        const entries: [string, unknown][] = item.payload.stepProperties
            ? Object.entries(item.payload.stepProperties)
            : [['error', 'No step properties available']]

        return <PropertiesTable entries={entries} alternatingColors={false} />
    },
}

/**
 * In-memory loader for exception steps (derived from event properties, no API calls).
 */
export class ExceptionStepLoader implements ItemLoader<ExceptionStepItem> {
    private readonly items: ExceptionStepItem[]

    constructor(exceptionUuid: string, properties?: ErrorEventProperties) {
        this.items = buildExceptionStepItems(exceptionUuid, properties)
    }

    async loadBefore(cursor: Dayjs, limit: number): Promise<{ items: ExceptionStepItem[]; hasMoreBefore: boolean }> {
        const before = this.items.filter((item) => item.timestamp.isBefore(cursor))
        return {
            items: before.slice(-limit),
            hasMoreBefore: before.length > limit,
        }
    }

    async loadAfter(cursor: Dayjs, limit: number): Promise<{ items: ExceptionStepItem[]; hasMoreAfter: boolean }> {
        const after = this.items.filter((item) => item.timestamp.isAfter(cursor))
        return {
            items: after.slice(0, limit),
            hasMoreAfter: after.length > limit,
        }
    }
}

// ─── Step item builders ──────────────────────────────────────────────────────

function buildExceptionStepItems(exceptionUuid: string, properties?: ErrorEventProperties): ExceptionStepItem[] {
    const runtime = getRuntimeFromLib(properties?.$lib)
    const rawSteps = properties?.$exception_steps

    if (rawSteps == null) {
        return []
    }

    if (!Array.isArray(rawSteps)) {
        return []
    }

    const validItems: ExceptionStepItem[] = []

    rawSteps.forEach((step, stepIndex) => {
        const item = buildStepItem({
            exceptionUuid,
            runtime,
            step,
            stepIndex,
        })

        if (item) {
            validItems.push(item)
        }
    })

    return validItems.sort((a, b) => {
        const timestampDiff = a.timestamp.diff(b.timestamp)
        if (timestampDiff !== 0) {
            return timestampDiff
        }
        return (a.sortPriority ?? 0) - (b.sortPriority ?? 0)
    })
}

function buildStepItem({
    exceptionUuid,
    runtime,
    step,
    stepIndex,
}: {
    exceptionUuid: string
    runtime: ErrorTrackingRuntime
    step: unknown
    stepIndex: number
}): ExceptionStepItem | null {
    const malformedReason = getExceptionStepMalformedReason(step)
    if (malformedReason) {
        return null
    }

    const rawStep = step as RawExceptionStep
    const type =
        typeof rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.TYPE] === 'string' &&
        rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.TYPE].trim()
            ? rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.TYPE]
            : undefined
    const message =
        typeof rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.MESSAGE] === 'string' &&
        rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.MESSAGE].trim()
            ? rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.MESSAGE]
            : ''
    const level =
        typeof rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.LEVEL] === 'string' &&
        rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.LEVEL].trim()
            ? rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.LEVEL]
            : undefined
    const timestamp = parseStepTimestamp(rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.TIMESTAMP])
    if (!timestamp) {
        return null
    }

    return {
        id: `${exceptionUuid}-exception-step-${stepIndex}`,
        category: ItemCategory.EXCEPTION_STEPS,
        timestamp,
        sortPriority: -1000 + stepIndex,
        payload: {
            runtime,
            type,
            message,
            level,
            stepProperties: { ...(step as Record<string, unknown>) },
            stepIndex,
        },
    }
}

function parseStepTimestamp(value: unknown): Dayjs | null {
    if (typeof value !== 'string' && typeof value !== 'number') {
        return null
    }

    const parsed = dayjs.utc(value)
    return parsed.isValid() ? parsed : null
}
