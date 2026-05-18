import clsx from 'clsx'

import { IconLock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

interface UsageLimitPaywallProps {
    title: string
    description?: React.ReactNode
    limit: number
    currentUsage?: number
    unit?: string
    ctaLabel?: string
    ctaTo?: string
    className?: string
    background?: boolean
}

export function UsageLimitPaywall({
    title,
    description,
    limit,
    currentUsage,
    unit = 'allowed on your plan',
    ctaLabel = 'View plans',
    ctaTo = urls.organizationBilling(),
    className,
    background = true,
}: UsageLimitPaywallProps): JSX.Element {
    return (
        <div
            className={clsx(
                className,
                background && 'bg-primary border border-primary',
                'PayGateMini rounded flex flex-col items-center p-4 text-center'
            )}
        >
            <div className="flex mb-2 text-4xl text-warning">
                <IconLock />
            </div>
            <h2>{title}</h2>
            {description && <p className="max-w-140">{description}</p>}
            <p className="p-4 border rounded border-primary bg-primary">
                <b>{limit}</b> {unit}
                {currentUsage !== undefined && (
                    <span className="text-secondary"> ({currentUsage} currently in use)</span>
                )}
            </p>
            <LemonButton type="primary" center to={ctaTo}>
                {ctaLabel}
            </LemonButton>
        </div>
    )
}
