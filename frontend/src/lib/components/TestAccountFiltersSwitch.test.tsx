import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { TestAccountFilterSwitch } from './TestAccountFiltersSwitch'

describe('TestAccountFilterSwitch — gear icon links to internal test filtering settings', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('navigates to the project product analytics settings, scrolled to internal-user-filtering', () => {
        render(<TestAccountFilterSwitch checked={false} onChange={jest.fn()} />)

        // The LemonSwitch itself has role="switch"; the gear is rendered as a link.
        // The router prepends a `/project/<id>` prefix to the href, so match the suffix.
        const gear = screen.getByRole('link')
        expect(gear.getAttribute('href')).toMatch(/\/settings\/project-product-analytics#internal-user-filtering$/)
    })
})
