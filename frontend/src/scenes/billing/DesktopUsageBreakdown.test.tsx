import { render, screen } from '@testing-library/react'

import { DesktopUsageBreakdown, getDesktopUsageComponents } from './DesktopUsageBreakdown'

describe('DesktopUsageBreakdown', () => {
    it('converts credits and resource quantities for display', () => {
        render(
            <DesktopUsageBreakdown
                summary={{
                    posthog_code_token_credits: { usage: 1234 },
                    sandbox_compute_credits: { usage: 266 },
                    sandbox_compute_cpu_millicore_seconds: { usage: 1500 },
                    sandbox_compute_memory_mib_seconds: { usage: 4608 },
                }}
            />
        )
        expect(screen.getByText('$12.34')).toBeTruthy()
        expect(screen.getByText('$2.66')).toBeTruthy()
        expect(screen.getByText('1.5 core-seconds')).toBeTruthy()
        expect(screen.getByText('4.5 GiB-seconds')).toBeTruthy()
    })

    it('shows missing data as unavailable and preserves explicit zero', () => {
        render(
            <DesktopUsageBreakdown
                summary={{
                    posthog_code_token_credits: { usage: 0 },
                    sandbox_compute_credits: { usage: null },
                }}
            />
        )
        expect(screen.getByText('$0.00')).toBeTruthy()
        expect(screen.getAllByText('Unavailable')).toHaveLength(3)
    })

    it('shows an awaiting-data state when the breakdown is absent', () => {
        render(<DesktopUsageBreakdown summary={undefined} />)
        expect(screen.getByText(/awaiting data/i)).toBeTruthy()
        expect(getDesktopUsageComponents(undefined)).toBeNull()
    })
})
