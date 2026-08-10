import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import SessionRecordingTemplates from './SessionRecordingTemplates'

describe('<SessionRecordingTemplates />', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('collapsed card keeps the hover-scale effect, expanded card drops it', async () => {
        const { container } = render(<SessionRecordingTemplates />)
        const card = container.querySelector('[data-ph-capture-attribute-template="purchase-flow"]') as HTMLElement
        expect(card).toHaveClass('LemonCard--hoverEffect')

        await userEvent.click(screen.getByText('Purchase flow'))

        const expandedCard = container.querySelector(
            '[data-ph-capture-attribute-template="purchase-flow"]'
        ) as HTMLElement
        expect(expandedCard).not.toHaveClass('LemonCard--hoverEffect')
        expect(screen.getByText('Apply filters')).toBeInTheDocument()
    })
})
