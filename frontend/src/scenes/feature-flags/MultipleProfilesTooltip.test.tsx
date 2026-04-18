import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { MULTIPLE_PROFILES_TOOLTIP_TEXT, MultipleProfilesTooltip } from './MultipleProfilesTooltip'

describe('MultipleProfilesTooltip', () => {
    it('clarifies that the count is matching person profiles, not distinct end users', () => {
        expect(MULTIPLE_PROFILES_TOOLTIP_TEXT).toContain('person profiles')
        expect(MULTIPLE_PROFILES_TOOLTIP_TEXT).toContain('multiple profiles')
        expect(MULTIPLE_PROFILES_TOOLTIP_TEXT).toContain('distinct end users')
    })

    it('renders an info icon as the tooltip trigger', () => {
        const { container } = render(<MultipleProfilesTooltip />)
        expect(container.querySelector('svg')).toBeInTheDocument()
    })
})
