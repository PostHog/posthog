import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { BillingType } from '~/types'

type UsageSummary = BillingType['usage_summary']

export interface DesktopUsageComponents {
    tokenCredits: number | null
    computeCredits: number | null
    cpuMillicoreSeconds: number | null
    memoryMibSeconds: number | null
}

const componentValue = (summary: UsageSummary, key: string): number | null => {
    const component = summary?.[key]
    return component?.usage == null ? null : component.usage + (component.todays_usage ?? 0)
}

export const getDesktopUsageComponents = (summary: UsageSummary): DesktopUsageComponents | null => {
    const keys = [
        'posthog_code_token_credits',
        'sandbox_compute_credits',
        'sandbox_compute_cpu_millicore_seconds',
        'sandbox_compute_memory_mib_seconds',
    ]
    if (!summary || !keys.some((key) => key in summary)) {
        return null
    }
    return {
        tokenCredits: componentValue(summary, keys[0]),
        computeCredits: componentValue(summary, keys[1]),
        cpuMillicoreSeconds: componentValue(summary, keys[2]),
        memoryMibSeconds: componentValue(summary, keys[3]),
    }
}

const formatQuantity = (value: number, divisor: number, unit: string): string =>
    `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value / divisor)} ${unit}`

const MixLegend = ({
    color,
    label,
    percent,
    value,
}: {
    color: string
    label: string
    percent: number
    value: string
}): JSX.Element => (
    <div className="flex items-center gap-2 text-sm">
        <span className={`size-2 rounded-full ${color}`} />
        <span>
            <strong>{percent}%</strong> {label}
            <span className="text-secondary"> · {value}</span>
        </span>
    </div>
)

export const DesktopUsageBreakdown = ({ summary }: { summary: UsageSummary }): JSX.Element | null => {
    const components = getDesktopUsageComponents(summary)
    if (components?.tokenCredits == null || components.computeCredits == null) {
        return null
    }

    const totalCredits = components.tokenCredits + components.computeCredits
    const tokenPercent = totalCredits > 0 ? (components.tokenCredits / totalCredits) * 100 : 0
    const roundedTokenPercent = Math.round(tokenPercent)
    const computePercent = totalCredits > 0 ? 100 - roundedTokenPercent : 0
    const resourceDetails = [
        components.cpuMillicoreSeconds == null
            ? 'CPU unavailable'
            : formatQuantity(components.cpuMillicoreSeconds, 1_000, 'core-seconds'),
        components.memoryMibSeconds == null
            ? 'Memory unavailable'
            : formatQuantity(components.memoryMibSeconds, 1_024, 'GiB-seconds'),
    ].join(' · ')

    return (
        <div className="mt-4 rounded bg-bg-light p-4 space-y-3">
            <h4 className="mb-0">Usage mix</h4>
            <div
                role="img"
                aria-label={`${roundedTokenPercent}% tokens and ${computePercent}% cloud compute`}
                className="flex h-3 w-full overflow-hidden rounded-full bg-border"
            >
                {totalCredits > 0 && (
                    <>
                        <div className="bg-accent" style={{ width: `${roundedTokenPercent}%` }} />
                        <div className="flex-1 bg-[var(--data-color-2)]" />
                    </>
                )}
            </div>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                <MixLegend
                    color="bg-accent"
                    label="Tokens"
                    percent={roundedTokenPercent}
                    value={humanFriendlyCurrency(components.tokenCredits / 100)}
                />
                <MixLegend
                    color="bg-[var(--data-color-2)]"
                    label="Cloud compute"
                    percent={computePercent}
                    value={humanFriendlyCurrency(components.computeCredits / 100)}
                />
            </div>
            <p className="mb-0 text-xs text-secondary">Compute resources: {resourceDetails}</p>
            <p className="mb-0 text-xs text-secondary">Usage reporting may be delayed by 15–20 minutes.</p>
        </div>
    )
}
