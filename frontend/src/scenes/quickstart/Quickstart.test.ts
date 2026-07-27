import { ProductKey } from '~/queries/schema/schema-general'

import { InstallationProgress } from '../onboarding/shared/wizard-sync/installationProgressLogic'
import { isQuickstartProductInstalling } from './QuickstartWizardProgress'

function progress(phase: InstallationProgress['phase']): InstallationProgress {
    return { phase, steps: [], error: null, prUrl: null, prMerged: false, isCurrent: true }
}

describe('Quickstart wizard integration', () => {
    test.each([
        ['connecting', true],
        ['running', true],
        ['completed', false],
        ['error', false],
        ['idle', false],
    ] as const)('marks Product analytics as installing while the wizard is %s', (phase, expected) => {
        expect(isQuickstartProductInstalling(ProductKey.PRODUCT_ANALYTICS, progress(phase))).toBe(expected)
    })

    it('does not infer installation progress for other products', () => {
        expect(isQuickstartProductInstalling(ProductKey.AI_OBSERVABILITY, progress('running'))).toBe(false)
    })
})
