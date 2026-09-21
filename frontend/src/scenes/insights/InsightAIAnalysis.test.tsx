import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { InsightAIAnalysis } from './InsightAIAnalysis'

jest.mock('./insightLogic', () => {
    const { kea, selectors } = jest.requireActual('kea')
    return {
        insightLogic: kea([
            selectors({
                insight: [() => [], () => ({ id: 1, short_id: 'abc123' })],
                insightProps: [() => [], () => ({ dashboardItemId: 'abc123' })],
            }),
        ]),
    }
})

jest.mock('./insightVizDataLogic', () => {
    const { kea, selectors } = jest.requireActual('kea')
    const logic = kea([selectors({ insightDataLoading: [() => [], () => false] })])
    return { insightVizDataLogic: () => logic }
})

jest.mock('scenes/organizationLogic', () => {
    const { kea, selectors } = jest.requireActual('kea')
    return {
        organizationLogic: kea([
            selectors({
                isAdminOrOwner: [() => [], () => true],
                currentOrganization: [() => [], () => ({ id: 'org-1' })],
            }),
        ]),
    }
})

jest.mock('scenes/settings/organization/aiConsentLogic', () => {
    const { kea, selectors } = jest.requireActual('kea')
    return {
        aiConsentLogic: kea([
            selectors({
                dataProcessingAccepted: [() => [], () => false],
                dataProcessingDismissed: [() => [], () => true],
                dataProcessingApprovalDisabledReason: [() => [], () => null],
            }),
        ]),
    }
})

describe('InsightAIAnalysis', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // A click without consent only prefills the composer, so a consent popover hidden by an earlier
    // dismissal left the button doing nothing at all.
    it('asks for consent even after an earlier dismissal', () => {
        render(<InsightAIAnalysis />)

        expect(screen.getByText('I allow AI analysis in this organization')).toBeInTheDocument()
    })
})
