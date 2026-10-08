import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { ContextDisplay } from './Context'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('lib/components/TaxonomicPopover/TaxonomicPopover', () => ({
    TaxonomicPopover: ({ onOpen }: { onOpen?: () => void }) => <button onClick={onOpen}>Add context</button>,
}))

jest.mock('./components/ModeSelector', () => ({ ModeSelector: () => null }))

jest.mock('./maxThreadLogic', () => ({ maxThreadLogic: { __mock: 'maxThreadLogic' } }))

describe('ContextDisplay', () => {
    it('loads dashboard context when the rendered context control opens', () => {
        const openContextPicker = jest.fn()
        ;(useValues as jest.Mock).mockReturnValue({
            showContextUI: true,
            contextDisabledReason: null,
            conversation: null,
            sandboxConversationKey: null,
            hasData: false,
            contextOptions: [],
            taxonomicGroupTypes: [],
            mainTaxonomicGroupType: 'events',
            toolContextItems: [],
            contextInsights: [],
            contextDashboards: [],
            contextEvents: [],
            contextActions: [],
            contextErrorTrackingIssues: [],
            contextNotebooks: [],
            contextEvaluations: [],
            chipsForDisplay: [],
        })
        ;(useActions as jest.Mock).mockReturnValue({
            handleTaxonomicFilterChange: jest.fn(),
            openContextPicker,
            detach: jest.fn(),
            removeContextInsight: jest.fn(),
            removeContextDashboard: jest.fn(),
            removeContextEvent: jest.fn(),
            removeContextAction: jest.fn(),
            removeContextErrorTrackingIssue: jest.fn(),
            removeContextNotebook: jest.fn(),
            removeContextEvaluation: jest.fn(),
        })

        render(<ContextDisplay />)

        fireEvent.click(screen.getByText('Add context'))

        expect(openContextPicker).toHaveBeenCalledTimes(1)
    })
})
