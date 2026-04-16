import { IconList } from '@posthog/icons'

import {
    EXCEPTION_STEP_INTERNAL_FIELDS,
    RawExceptionStep,
    getExceptionStepMalformedReason,
} from 'lib/components/Errors/exceptionStepsValidation'
import { ErrorEventProperties, ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { Dayjs, dayjs } from 'lib/dayjs'

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
        const stepProperties = getRenderableStepProperties(item.payload.stepProperties)

        return <SimpleKeyValueList item={stepProperties} emptyMessage="No additional step properties" />
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
    const rawType = rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.TYPE]
    const rawMessage = rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.MESSAGE]
    const rawLevel = rawStep[EXCEPTION_STEP_INTERNAL_FIELDS.LEVEL]

    const type = typeof rawType === 'string' && rawType.trim() ? rawType : undefined
    const message = typeof rawMessage === 'string' && rawMessage.trim() ? rawMessage : ''
    const level = typeof rawLevel === 'string' && rawLevel.trim() ? rawLevel : undefined
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

const INTERNAL_STEP_FIELD_SET = new Set<string>(Object.values(EXCEPTION_STEP_INTERNAL_FIELDS))

function getRenderableStepProperties(stepProperties?: Record<string, unknown>): Record<string, unknown> {
    if (!stepProperties) {
        return {}
    }

    return Object.fromEntries(Object.entries(stepProperties).filter(([key]) => !INTERNAL_STEP_FIELD_SET.has(key)))
}
