import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SurveyType } from '~/types'

import { Customization } from './SurveyCustomization'

describe('Customization', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/surveys/': { results: [], count: 0 },
                '/api/projects/:team_id/surveys/responses_count/': {},
            },
        })
    })

    const baseProps = {
        survey: { type: SurveyType.API, appearance: { whiteLabel: false }, questions: [] } as any,
        onAppearanceChange: jest.fn(),
        hasRatingButtons: false,
        hasPlaceholderText: false,
        hasBranchingLogic: false,
    }

    it('renders only the branding control when onlyBranding is set (API surveys)', () => {
        render(<Customization {...baseProps} onlyBranding />)

        expect(screen.getByText('Hide PostHog branding')).toBeInTheDocument()
        // the styling sections must not render in branding only mode.
        expect(screen.queryByText('Theme')).not.toBeInTheDocument()
        expect(screen.queryByText('Colors')).not.toBeInTheDocument()
        expect(screen.queryByText('Behavior')).not.toBeInTheDocument()
    })
})
