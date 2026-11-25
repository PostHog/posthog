import { IconCheckCircle } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

import { PartnerReviewApi } from '~/generated/core/api.schemas'

import { REVIEW_COMPLETE, reviewProgress } from '../oauthAppProvisioningStatus'

export function QuillOAuthAppReviewProgress({ review }: { review: PartnerReviewApi }): JSX.Element {
    const { steps, currentStep } = reviewProgress(review)
    const currentIndex =
        currentStep === REVIEW_COMPLETE ? steps.length : steps.findIndex(({ step }) => step === currentStep)

    return (
        <ol className="m-0 p-0 list-none flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Review progress">
            {steps.map(({ step, label }, index) => {
                const isCurrent = index === currentIndex
                return (
                    <li key={step} className="flex items-center gap-1.5" aria-current={isCurrent ? 'step' : undefined}>
                        {index < currentIndex ? (
                            <IconCheckCircle className="size-4 text-success-foreground" />
                        ) : (
                            <span
                                className={cn(
                                    'flex items-center justify-center size-4 rounded-full text-xxs font-semibold',
                                    isCurrent
                                        ? 'bg-primary text-primary-foreground'
                                        : 'border border-border text-muted-foreground'
                                )}
                            >
                                {index + 1}
                            </span>
                        )}
                        <Text
                            size="xs"
                            weight={isCurrent ? 'semibold' : undefined}
                            variant={index > currentIndex ? 'muted' : undefined}
                            render={<span />}
                        >
                            {label}
                        </Text>
                    </li>
                )
            })}
        </ol>
    )
}
