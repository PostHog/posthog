import { BridgePage } from 'lib/components/BridgePage/BridgePage'

export const OnboardingStep = ({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle?: string
    children: React.ReactNode
}): JSX.Element => {
    return (
        <BridgePage view="onboarding-step" noLogo hedgehog={false} fixedWidth={false}>
            <div className="max-w-md">
                <h1>{title}</h1>
                <p>{subtitle}</p>
                {children}
            </div>
        </BridgePage>
    )
}
