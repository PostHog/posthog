import { experimentResultsWidgetConfigSchema } from '../../generated/widget-configs.zod'
import {
    patchExperimentResultsWidgetConfig,
    validateExperimentResultsWidgetConfigInput,
} from './experimentResultsWidgetConfigValidation'

describe('experimentResultsWidgetConfigValidation', () => {
    it('accepts a selected experiment', () => {
        const result = validateExperimentResultsWidgetConfigInput({ experimentId: 123 })
        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.experimentId).toBe(123)
        }
    })

    it('sets the selected experiment on an existing config', () => {
        const base = experimentResultsWidgetConfigSchema.parse({})
        const next = patchExperimentResultsWidgetConfig(base, 123)
        expect(next.experimentId).toBe(123)
    })

    it('clears the selection back to null', () => {
        const base = experimentResultsWidgetConfigSchema.parse({ experimentId: 123 })
        const next = patchExperimentResultsWidgetConfig(base, null)
        expect(next.experimentId ?? null).toBeNull()
    })
})
