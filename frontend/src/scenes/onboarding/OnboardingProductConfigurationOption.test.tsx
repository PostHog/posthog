import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { OnboardingProductConfigurationOption } from './OnboardingProductConfigurationOption'

describe('OnboardingProductConfigurationOption', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        { value: false, expected: true },
        { value: true, expected: false },
    ])('clicking the toggle title flips it from $value to $expected', ({ value, expected }) => {
        const onChange = jest.fn()
        render(
            <OnboardingProductConfigurationOption
                teamProperty="heatmaps_opt_in"
                title="Enable heatmaps"
                type="toggle"
                value={value}
                onChange={onChange}
            />
        )

        fireEvent.click(screen.getByText('Enable heatmaps'))

        expect(onChange).toHaveBeenCalledWith(expected)
    })
})
