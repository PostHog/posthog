import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { MULTIPLE_PROFILES_TOOLTIP_TEXT, MultipleProfilesTooltip } from './MultipleProfilesTooltip'

describe('MultipleProfilesTooltip', () => {
    it.each(['person profiles', 'multiple profiles', 'distinct end users'])('tooltip text contains "%s"', (phrase) => {
        expect(MULTIPLE_PROFILES_TOOLTIP_TEXT).toContain(phrase)
    })

    it('renders an info icon as the tooltip trigger', () => {
        const { container } = render(<MultipleProfilesTooltip />)
        expect(container.querySelector('svg')).toBeInTheDocument()
    })
})
