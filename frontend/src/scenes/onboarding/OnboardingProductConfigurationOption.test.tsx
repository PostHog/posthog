import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { OnboardingProductConfigurationOption } from './OnboardingProductConfigurationOption'

describe('OnboardingProductConfigurationOption', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        { value: false, expected: true, disabledReason: undefined },
        { value: true, expected: false, disabledReason: undefined },
        { value: false, expected: undefined, disabledReason: 'Ask a project admin to change this setting.' },
    ])(
        'clicking the toggle title respects its disabled state ($value, $disabledReason)',
        ({ value, expected, disabledReason }) => {
            const onChange = jest.fn()
            render(
                <OnboardingProductConfigurationOption
                    teamProperty="heatmaps_opt_in"
                    title="Enable heatmaps"
                    type="toggle"
                    value={value}
                    onChange={onChange}
                    disabledReason={disabledReason}
                />
            )

            fireEvent.click(screen.getByText('Enable heatmaps'))

            if (disabledReason) {
                expect(onChange).not.toHaveBeenCalled()
            } else {
                expect(onChange).toHaveBeenCalledWith(expected)
            }
        }
    )
})
