import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

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

    // Guards the fix for the "dead toggle" papercut: without explainWhenNoFilters the reason why the
    // disabled switch can't be turned on lives only in a hover tooltip, so it reads as broken.
    it('surfaces the no-filters reason as visible text when explainWhenNoFilters is set', () => {
        render(<TestAccountFilterSwitch checked={false} onChange={jest.fn()} explainWhenNoFilters />)

        expect(screen.getByText(/haven't set any internal test filters yet/i)).toBeInTheDocument()
    })

    it('does not surface the reason text by default (tooltip only)', () => {
        render(<TestAccountFilterSwitch checked={false} onChange={jest.fn()} />)

        expect(screen.queryByText(/haven't set any internal test filters yet/i)).not.toBeInTheDocument()
    })
})
