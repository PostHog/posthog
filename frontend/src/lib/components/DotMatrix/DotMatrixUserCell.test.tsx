import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DotMatrixUserCell } from './DotMatrixUserCell'

describe('DotMatrixUserCell', () => {
    afterEach(cleanup)

    it('opens the full caller-supplied name list on activation', async () => {
        const persons = ['Ada', 'Bo', 'Cy', 'Di'].map((name) => ({ id: name, name, email: `${name}@example.com` }))
        render(<DotMatrixUserCell persons={persons} />)
        fireEvent.click(screen.getByTestId('dot-matrix-more-users'))
        expect(await screen.findByText('Di@example.com')).toBeTruthy()
    })

    it('renders caller-specific details without product fixture fields', async () => {
        render(
            <DotMatrixUserCell
                persons={[{ id: 'reviewer', name: 'Avery', checks: 7 }]}
                renderTooltip={(person) => <span>{`${person.checks} reviews completed`}</span>}
            />
        )
        fireEvent.focus(screen.getByText('Avery'))
        expect(await screen.findByText('7 reviews completed')).toBeTruthy()
    })
})
