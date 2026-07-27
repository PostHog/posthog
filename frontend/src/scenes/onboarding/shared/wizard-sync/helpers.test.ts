import { activeStep, prName } from './helpers'
import type { InstallationStep } from './installationProgressLogic'

describe('wizard-sync helpers', () => {
    it('activeStep prefers the wizard sub-step over the pipeline stage containing it', () => {
        // The card headline would otherwise read "Running setup wizard" while the wizard is
        // reporting something more specific like "Install SDK".
        const stage: InstallationStep = {
            id: 'setup:wizard',
            label: 'Running setup wizard',
            status: 'in_progress',
            detail: null,
        }
        const sub: InstallationStep = {
            id: 'wizard-task:a',
            label: 'Install SDK',
            status: 'in_progress',
            detail: null,
            source: 'wizard',
        }
        expect(activeStep([stage, sub])?.label).toBe('Install SDK')
        expect(activeStep([stage])?.label).toBe('Running setup wizard')
        expect(activeStep([])).toBeNull()
    })

    // The PR CTA interpolates this into the button label — a bad parse would render
    // "Review null" or leak a mangled identifier instead of falling back to "Review PR".
    it.each([
        ['https://github.com/acme-co/web/pull/42', 'acme-co/web#42'],
        ['https://github.com/acme-co/web/pull/42/files', 'acme-co/web#42'],
        ['https://github.com/acme-co/web/pull/42?diff=split', 'acme-co/web#42'],
        ['https://github.example.com/acme-co/web/pull/7', 'acme-co/web#7'],
        ['https://gitlab.com/acme-co/web/-/merge_requests/42', null],
        ['https://github.com/acme-co/web', null],
        ['not a url', null],
    ])('prName(%s) → %s', (url, expected) => {
        expect(prName(url)).toBe(expected)
    })
})
