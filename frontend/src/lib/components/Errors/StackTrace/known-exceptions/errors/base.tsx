import { LemonBanner } from '@posthog/lemon-ui'

export function KnownErrorBanner({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <LemonBanner type="info" className="bg-surface-secondary">
            {children}
        </LemonBanner>
    )
}
