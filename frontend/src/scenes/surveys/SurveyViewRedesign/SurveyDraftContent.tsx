import { IconRocket } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { BuilderHog1 } from 'lib/components/hedgehogs'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'

export function SurveyDraftContent({ onSeeSurveyDetails }: { onSeeSurveyDetails?: () => void }): JSX.Element {
    const launchChecklist = [
        {
            title: 'Question clarity',
            description: 'Keep wording short and specific so respondents can answer quickly.',
        },
        {
            title: 'Audience targeting',
            description: 'Confirm URL and user conditions so this shows to the right people.',
        },
        {
            title: 'Timing and frequency',
            description: 'Choose moments after value events, and avoid showing too often.',
        },
    ]

    return (
        <div className="px-4 py-10">
            <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 text-center">
                <div className="relative h-40 w-[320px] max-w-full">
                    <div className="absolute bottom-2 left-1/2 h-3 w-40 -translate-x-1/2 rounded-full bg-black/10 blur-sm" />
                    <div className="absolute left-1/2 top-0 z-20 max-w-[240px] -translate-x-1/2 rounded-full border bg-surface-primary px-3 py-1 text-xs text-secondary shadow-sm">
                        Ready when you are
                        <svg
                            className="absolute left-1/2 top-full -translate-x-1/2 -translate-y-px"
                            width="14"
                            height="7"
                            viewBox="0 0 14 7"
                            fill="none"
                        >
                            <path d="M0 0 L7 6 L14 0" fill="var(--color-bg-surface-primary)" />
                            <path d="M0.5 0 L7 5.5 L13.5 0" stroke="var(--color-border)" strokeWidth="1" fill="none" />
                        </svg>
                    </div>
                    <BuilderHog1 className="absolute bottom-0 left-1/2 block size-36 -translate-x-1/2" />
                </div>

                <div className="flex flex-col items-center gap-3">
                    <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary-highlight">
                        <IconRocket className="text-3xl text-primary" />
                    </div>
                    <div>
                        <h2 className="m-0 mb-2 text-xl font-semibold">Ready to launch</h2>
                        <p className="m-0 text-muted">
                            Your survey is saved as a draft. Launch it to start collecting responses.
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <LaunchSurveyButton>Launch survey</LaunchSurveyButton>
                    <LemonButton type="tertiary" size="small" onClick={onSeeSurveyDetails}>
                        See survey details
                    </LemonButton>
                </div>

                <div className="w-full max-w-2xl">
                    <div className="mb-2 text-center text-sm font-medium text-primary">Pre-launch checklist</div>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                        {launchChecklist.map((item, index) => (
                            <div key={item.title} className="rounded-lg border border-border p-3 text-left">
                                <div className="mb-2 flex items-center gap-2">
                                    <span className="inline-flex size-5 items-center justify-center rounded-full border border-border text-xs text-secondary">
                                        {index + 1}
                                    </span>
                                    <span className="text-sm font-medium text-primary">{item.title}</span>
                                </div>
                                <p className="m-0 text-xs text-secondary">{item.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
