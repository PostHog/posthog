import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { TodayPulseMovers } from './TodayPulseMovers'

describe('TodayPulseMovers', () => {
    afterEach(() => cleanup())

    it('keeps the ranking it receives and shows each change', () => {
        render(
            <TodayPulseMovers
                movers={[
                    { label: 'Refunds', value: -50, change_pct: -20 },
                    { label: 'Orders', value: 120, change_pct: 10 },
                ]}
            />
        )

        expect(screen.getByText('−20%')).toBeInTheDocument()
        expect(screen.getByText('+10%')).toBeInTheDocument()
        expect(screen.getAllByRole('listitem').map((row) => row.textContent?.split(/[+−-]/)[0])).toEqual([
            'Refunds',
            'Orders',
        ])
    })
})
