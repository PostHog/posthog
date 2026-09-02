import '@testing-library/jest-dom'

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
        const usageMix = screen.getByLabelText('82% tokens and 18% cloud compute')
        expect(usageMix.firstElementChild).toHaveStyle({ width: '82%' })
        expect(screen.getByText(/\$12\.34/)).toBeTruthy()
        expect(screen.getByText(/\$2\.66/)).toBeTruthy()
        expect(screen.getByText(/1\.5 core-seconds · 4\.5 GiB-seconds/)).toBeTruthy()
    })

    it('preserves explicit zero', () => {
        render(
            <DesktopUsageBreakdown
                summary={{
                    posthog_code_token_credits: { usage: 0 },
                    sandbox_compute_credits: { usage: 0 },
                }}
            />
        )
        expect(screen.getByLabelText('0% tokens and 0% cloud compute')).toBeTruthy()
        expect(screen.getAllByText(/\$0\.00/)).toHaveLength(2)
        expect(screen.getByText(/CPU unavailable · Memory unavailable/)).toBeTruthy()
    })

    it('includes todays usage in component totals', () => {
        expect(
            getDesktopUsageComponents({
                posthog_code_token_credits: { usage: 1200, todays_usage: 34 },
                sandbox_compute_credits: { usage: 200, todays_usage: 66 },
            })
        ).toMatchObject({ tokenCredits: 1234, computeCredits: 266 })
    })

    it('hides the breakdown when credit components are absent or incomplete', () => {
        const { container, rerender } = render(<DesktopUsageBreakdown summary={undefined} />)
        expect(container).toBeEmptyDOMElement()
        expect(getDesktopUsageComponents(undefined)).toBeNull()

        rerender(<DesktopUsageBreakdown summary={{ posthog_code_token_credits: { usage: 0 } }} />)
        expect(container).toBeEmptyDOMElement()
    })
})
