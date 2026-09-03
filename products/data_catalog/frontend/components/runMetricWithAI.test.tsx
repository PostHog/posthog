import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { initKeaTests } from '~/test/init'

import { buildMetricRunPrompt, RunMetricWithAIButton } from './RunMetricWithAIButton'

jest.mock('scenes/settings/organization/aiConsentLogic', () => {
    const { kea, selectors } = jest.requireActual('kea')
    return {
        aiConsentLogic: kea([
            selectors({
                dataProcessingAccepted: [() => [], () => (global as any).__consentAccepted ?? false],
                dataProcessingDismissed: [() => [], () => false],
                dataProcessingApprovalDisabledReason: [() => [], () => null],
            }),
        ]),
    }
})

describe('RunMetricWithAIButton', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('tells the agent to read the definition from the catalog and to stay read-only', () => {
        const prompt = buildMetricRunPrompt('weekly_paying_customers')

        // Attached context only reaches the sandbox send path, so the prompt has to stand alone.
        expect(prompt).toContain("system.information_schema.metrics where name = 'weekly_paying_customers'")
        // The definition is project-authored, so a stored-injection attempt must not read as intent.
        expect(prompt).toContain('untrusted data')
        expect(prompt).toContain('do not create, modify, or delete anything')
    })

    it.each([
        ['consent already given', true, 1],
        ['consent not yet given', false, 0],
    ])('runs %s exactly %s time(s) per click', (_label, accepted, expectedRuns) => {
        ;(global as any).__consentAccepted = accepted
        aiConsentLogic.mount()
        const onRun = jest.fn()

        render(<RunMetricWithAIButton onRun={onRun} />)
        fireEvent.click(screen.getByText('Run with AI'))

        // Without the guard an unapproved click fires here and again from the consent popover's
        // onApprove, recording the run twice.
        expect(onRun).toHaveBeenCalledTimes(expectedRuns)
    })
})
