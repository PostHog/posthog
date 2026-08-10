import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { BillingType } from '~/types'

type UsageSummary = BillingType['usage_summary']

export interface DesktopUsageComponents {
    tokenCredits: number | null
    computeCredits: number | null
    cpuMillicoreSeconds: number | null
    memoryMibSeconds: number | null
}

const componentValue = (summary: UsageSummary, key: string): number | null => summary?.[key]?.usage ?? null

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

const ComponentCard = ({ label, value }: { label: string; value: string | null }): JSX.Element => (
    <div className="border rounded p-4 bg-bg-light">
        <div className="text-sm text-secondary">{label}</div>
        <div className="font-semibold text-lg">{value ?? 'Unavailable'}</div>
    </div>
)

export const DesktopUsageBreakdown = ({ summary }: { summary: UsageSummary }): JSX.Element => {
    const components = getDesktopUsageComponents(summary)

    return (
        <div className="mt-4 space-y-3">
            <div>
                <h4 className="mb-1">Usage breakdown</h4>
                <p className="text-sm text-secondary mb-0">Usage reporting may be delayed by 15–20 minutes.</p>
            </div>
            {components ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    <ComponentCard
                        label="Tokens"
                        value={
                            components.tokenCredits == null
                                ? null
                                : humanFriendlyCurrency(components.tokenCredits / 100)
                        }
                    />
                    <ComponentCard
                        label="Cloud compute"
                        value={
                            components.computeCredits == null
                                ? null
                                : humanFriendlyCurrency(components.computeCredits / 100)
                        }
                    />
                    <ComponentCard
                        label="CPU usage"
                        value={
                            components.cpuMillicoreSeconds == null
                                ? null
                                : formatQuantity(components.cpuMillicoreSeconds, 1_000, 'core-seconds')
                        }
                    />
                    <ComponentCard
                        label="Memory usage"
                        value={
                            components.memoryMibSeconds == null
                                ? null
                                : formatQuantity(components.memoryMibSeconds, 1_024, 'GiB-seconds')
                        }
                    />
                </div>
            ) : (
                <LemonBanner type="info">
                    Detailed usage is awaiting data. Combined Desktop spend and the organization limit remain available
                    above.
                </LemonBanner>
            )}
        </div>
    )
}
