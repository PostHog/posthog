import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { SurveyColorsAppearance } from './SurveyAppearanceSections'

describe('SurveyColorsAppearance', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('offers the sample placeholder as a hint, not as a stored value', () => {
        render(
            <SurveyColorsAppearance
                appearance={{}}
                onAppearanceChange={jest.fn()}
                customizeRatingButtons={false}
                customizePlaceholderText={true}
            />
        )

        expect(screen.getByPlaceholderText('Start typing...')).toHaveValue('')
    })
})
