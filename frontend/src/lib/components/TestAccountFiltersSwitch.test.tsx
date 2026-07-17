import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { TestAccountFilterSwitch } from './TestAccountFiltersSwitch'

describe('TestAccountFilterSwitch', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('gear icon navigates to the project product analytics settings, scrolled to internal-user-filtering', () => {
        render(<TestAccountFilterSwitch checked={false} onChange={jest.fn()} />)

        // The LemonSwitch itself has role="switch"; the gear is rendered as a link.
        // The router prepends a `/project/<id>` prefix to the href, so match the suffix.
        const gear = screen.getByRole('link')
        expect(gear.getAttribute('href')).toMatch(/\/settings\/project-product-analytics#internal-user-filtering$/)
    })

    it('clicking "Unset override" calls onReset without toggling the switch', () => {
        const onChange = jest.fn()
        const onReset = jest.fn()
        render(<TestAccountFilterSwitch checked={true} onChange={onChange} onReset={onReset} />)

        // The reset link sits inside the switch's <label> — a forwarded click would also toggle the switch
        fireEvent.click(screen.getByText('Unset override'))

        expect(onReset).toHaveBeenCalledTimes(1)
        expect(onChange).not.toHaveBeenCalled()
    })
})
