import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { PagePerformanceCardHeader } from './PagePerformanceCardHeader'

const DESCRIPTION = 'Share of the answers that cite one of your pages.'

describe('PagePerformanceCardHeader', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the description when the info button is clicked', async () => {
        render(<PagePerformanceCardHeader title="Answers that cite you" description={DESCRIPTION} />)

        fireEvent.click(screen.getByLabelText('About Answers that cite you'))

        expect(await screen.findByText(DESCRIPTION)).toBeTruthy()
    })
})
