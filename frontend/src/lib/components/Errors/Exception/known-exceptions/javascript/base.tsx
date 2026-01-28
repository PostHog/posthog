import { LemonBanner } from '@posthog/lemon-ui'

export function KnownExceptionBanner({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <LemonBanner type="info" className="bg-surface-secondary">
            {children}
        </LemonBanner>
    )
}
