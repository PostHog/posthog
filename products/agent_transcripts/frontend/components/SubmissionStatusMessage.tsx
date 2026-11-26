import { WizardHog } from 'scenes/onboarding/shared/wizardHog'

export interface SubmissionStatusMessageProps {
    title: string
    children: React.ReactNode
    'data-attr': string
}

/** A resolved submission: in review, approved or declined. */
export function SubmissionStatusMessage({
    title,
    children,
    'data-attr': dataAttr,
}: SubmissionStatusMessageProps): JSX.Element {
    return (
        <section
            className="flex items-start gap-5 rounded border border-primary bg-surface-primary p-6"
            data-attr={dataAttr}
        >
            {/* The hog is decoration, so it is the first thing a narrow scene drops. */}
            <WizardHog className="hidden size-20 shrink-0 @min-[32rem]/main-content:block" loading="eager" />
            <div className="flex min-w-0 flex-col gap-2">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                {children}
            </div>
        </section>
    )
}
