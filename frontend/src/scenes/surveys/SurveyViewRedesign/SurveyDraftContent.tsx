import { useValues } from 'kea'

import { IconCheck, IconRocket } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { BuilderHog1 } from 'lib/components/hedgehogs'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { Survey, SurveyType } from '~/types'

interface ChecklistItem {
    title: string
    done: boolean
    hint: string
}

function getLaunchChecklist(survey: Survey, hasTargetingSet: boolean): ChecklistItem[] {
    const hasQuestions = survey.questions.length > 0
    const allQuestionsHaveText = hasQuestions && survey.questions.every((q) => q.question?.trim())

    const isApiSurvey = survey.type === SurveyType.API
    const hasDisplayConditions =
        isApiSurvey ||
        !!survey.conditions?.url ||
        (survey.conditions?.events?.values?.length ?? 0) > 0 ||
        (survey.conditions?.actions?.values?.length ?? 0) > 0

    return [
        {
            title: 'Questions',
            done: hasQuestions && allQuestionsHaveText,
            hint: !hasQuestions
                ? 'Add at least one question to your survey.'
                : !allQuestionsHaveText
                  ? 'Make sure every question has text.'
                  : 'All questions have text.',
        },
        {
            title: 'Audience targeting',
            done: hasTargetingSet,
            hint: hasTargetingSet
                ? 'Targeting conditions are set.'
                : 'Add URL, user, or feature flag conditions so this reaches the right people.',
        },
        {
            title: 'Display conditions',
            done: hasDisplayConditions,
            hint: isApiSurvey
                ? 'API survey — you control when it shows.'
                : hasDisplayConditions
                  ? 'Trigger events or URL rules are configured.'
                  : 'Add a URL match or trigger event so the survey appears at the right moment.',
        },
    ]
}

export function SurveyDraftContent({ onSeeSurveyDetails }: { onSeeSurveyDetails?: () => void }): JSX.Element {
    const { survey, hasTargetingSet } = useValues(surveyLogic)
    const checklist = getLaunchChecklist(survey as Survey, hasTargetingSet)

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
                        {checklist.map((item) => (
                            <div key={item.title} className="rounded-lg border border-border p-3 text-left">
                                <div className="mb-2 flex items-center gap-2">
                                    <span
                                        className={`inline-flex size-5 items-center justify-center rounded-full text-xs ${
                                            item.done
                                                ? 'bg-success-highlight text-success'
                                                : 'border border-border text-secondary'
                                        }`}
                                    >
                                        {item.done ? <IconCheck className="size-3" /> : null}
                                    </span>
                                    <span className="text-sm font-medium text-primary">{item.title}</span>
                                </div>
                                <p className="m-0 text-xs text-secondary">{item.hint}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
