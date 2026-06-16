import { experimentsWidgetConfigSchema } from '../../generated/widget-configs.zod'
import {
    EXPERIMENTS_WIDGET_FORM_FIELD_NAMES,
    patchExperimentsListWidgetConfig,
    validateExperimentsListWidgetConfigInput,
} from './experimentsListWidgetConfigValidation'

describe('experimentsListWidgetConfigValidation', () => {
    it('form picked fields exist on the generated config schema', () => {
        const shape = experimentsWidgetConfigSchema.shape
        for (const field of EXPERIMENTS_WIDGET_FORM_FIELD_NAMES) {
            expect(shape).toHaveProperty(field)
        }
    })

    it('rejects limit above 25 with an inline-friendly message', () => {
        const result = validateExperimentsListWidgetConfigInput({ limit: 30, status: 'all', createdBy: null })
        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.fieldErrors.limit).toBe('Too big: expected number to be <=25')
        }
    })

    it('accepts a valid status + creator filter', () => {
        const result = validateExperimentsListWidgetConfigInput({ limit: 10, status: 'running', createdBy: 7 })
        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.limit).toBe(10)
            expect(result.config.status).toBe('running')
            expect(result.config.createdBy).toBe(7)
        }
    })

    it('patches status while preserving limit', () => {
        const base = experimentsWidgetConfigSchema.parse({ limit: 5, status: 'all', createdBy: 7 })
        const next = patchExperimentsListWidgetConfig(base, { status: 'paused' })
        expect(next.status).toBe('paused')
        expect(next.limit).toBe(5)
        expect(next.createdBy).toBe(7)
    })

    it('clears the creator filter without touching status', () => {
        const base = experimentsWidgetConfigSchema.parse({ limit: 5, status: 'running', createdBy: 7 })
        const next = patchExperimentsListWidgetConfig(base, { createdBy: null })
        expect(next.createdBy ?? null).toBeNull()
        expect(next.status).toBe('running')
    })
})
