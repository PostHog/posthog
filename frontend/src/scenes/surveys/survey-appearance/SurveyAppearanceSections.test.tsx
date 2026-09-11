import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, SurveyAppearance } from '~/types'

import { surveysLogic } from '../surveysLogic'
import { SurveyColorsAppearance, SurveyContainerAppearance } from './SurveyAppearanceSections'

describe('SurveyAppearanceSections', () => {
    const onAppearanceChange = jest.fn()

    beforeEach(async () => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: [{ key: AvailableFeature.SURVEYS_STYLING, name: 'Surveys styling' }],
        })
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
        })
        // Keep the logic the inputs read mounted, so its survey list settles before the render.
        surveysLogic.mount()
        await expectLogic(surveysLogic).toFinishAllListeners()
        onAppearanceChange.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    function renderAndBlur(element: JSX.Element, value: string): void {
        render(<Provider>{element}</Provider>)
        fireEvent.blur(screen.getByDisplayValue(value))
    }

    // Placeholder text is respondent-facing copy, so the CSS clean-up must not touch it.
    it.each(['Optional: add more detail', 'Tell us more;', 'Anything at all !important'])(
        'keeps the placeholder text %p as written',
        (placeholder) => {
            renderAndBlur(
                <SurveyColorsAppearance
                    appearance={{ placeholder } as SurveyAppearance}
                    onAppearanceChange={onAppearanceChange}
                    customizeRatingButtons={false}
                    customizePlaceholderText
                />,
                placeholder
            )

            expect(onAppearanceChange).not.toHaveBeenCalled()
        }
    )

    it('cleans a pasted declaration out of a CSS field', () => {
        const pastedValue = 'box-shadow: 0 4px 12px rgba(0,0,0,.15);'
        renderAndBlur(
            <SurveyContainerAppearance
                appearance={{ boxShadow: pastedValue } as SurveyAppearance}
                onAppearanceChange={onAppearanceChange}
            />,
            pastedValue
        )

        expect(onAppearanceChange).toHaveBeenCalledWith({ boxShadow: '0 4px 12px rgba(0,0,0,.15)' })
    })
})
