import * as motion from 'motion/react-client'

import { LemonButton } from '@posthog/lemon-ui'

import { DetectiveHog, SurprisedHog, WavingHog } from 'lib/components/hedgehogs'

interface Props {
    type: 'question' | 'survey'
    isFiltered?: boolean
    onClearFilters?: () => void
    activeFilterTypes?: {
        dateRange?: boolean
        answerFilters?: boolean
        propertyFilters?: boolean
    }
}

export function SurveyNoResponsesBanner({
    type,
    isFiltered = false,
    onClearFilters,
    activeFilterTypes,
}: Props): JSX.Element {
    const isSurveyWithoutResponses = type === 'survey' && !isFiltered
    const title = isFiltered
        ? 'No responses match current filters'
        : isSurveyWithoutResponses
          ? 'Your survey is live. Results will show up soon.'
          : `No responses for this ${type}`
    const description = isFiltered
        ? 'Try adjusting your filters to see matching responses.'
        : isSurveyWithoutResponses
          ? 'As soon as people answer this survey, you will see results here. Check back soon.'
          : `Once people start responding to your ${type}, their answers will appear here.`
    const bubbleText = isFiltered
        ? getFilterBubbleText(activeFilterTypes)
        : isSurveyWithoutResponses
          ? 'Waiting for first replies'
          : `No answers collected yet`
    const Hog = isFiltered ? DetectiveHog : isSurveyWithoutResponses ? WavingHog : SurprisedHog
    const hogDuration = isFiltered ? 1.2 : 1.1
    const hogAnimation = isFiltered
        ? {
              x: [0, -24, 0, 24, 0],
              y: [0, -3, 0, -3, 0],
              rotate: [0, -2, 0, 2, 0],
          }
        : {
              y: [0, -5, 0, -3, 0],
              rotate: [0, -4, 0, 2, 0],
          }
    const hogTransition = isFiltered
        ? {
              x: { duration: hogDuration, ease: 'easeInOut' },
              y: { duration: hogDuration, ease: 'easeInOut' },
              rotate: { duration: hogDuration, ease: 'easeInOut' },
          }
        : {
              y: { duration: hogDuration, delay: 0.1, ease: 'easeInOut' },
              rotate: { duration: hogDuration, delay: 0.1, ease: 'easeInOut' },
          }
    const quickTips = [
        {
            title: 'Start with one key question',
            description: 'Long surveys drop completion rates quickly. Keep the first ask simple and focused.',
        },
        {
            title: 'Ask at the right moment',
            description: 'Trigger after value moments like signup completion, feature usage, or a purchase.',
        },
        {
            title: 'Set context in one sentence',
            description: 'Explain why feedback matters so people feel their answer will lead to action.',
        },
    ]

    return (
        <div className="w-full rounded flex flex-col items-center justify-center gap-5 py-8">
            <div className="relative w-[380px] max-w-[90vw] h-42 overflow-hidden">
                <div className="absolute bottom-2 left-1/2 -translate-x-1/2 w-36 h-3 rounded-full bg-black/10 blur-sm" />
                <motion.div
                    className="absolute left-1/2 top-0 z-20 -translate-x-1/2 max-w-[220px] rounded-full border bg-surface-primary px-3 py-1 text-center text-xs text-secondary shadow-sm"
                    initial={{ opacity: 0, y: 4, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{
                        duration: 0.3,
                        delay: hogDuration + 0.2,
                        ease: 'easeOut',
                    }}
                >
                    {bubbleText}
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
                </motion.div>
                <motion.div
                    className="absolute bottom-1 left-1/2"
                    style={{ marginLeft: '-4.5rem' }}
                    initial={{ x: 0, y: 0, rotate: 0, opacity: 1 }}
                    animate={hogAnimation}
                    transition={hogTransition}
                >
                    <Hog className="size-36 block" loading="eager" decoding="sync" />
                </motion.div>
            </div>
            <div className="text-center max-w-2xl space-y-1">
                <h3 className="text-lg font-semibold m-0">{title}</h3>
                <p className="text-sm text-muted m-0">{description}</p>
            </div>
            {isSurveyWithoutResponses && (
                <div className="w-full max-w-2xl px-4">
                    <div className="text-sm font-medium text-primary mb-2 text-center">
                        Quick ways to get first responses
                    </div>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                        {quickTips.map((tip, index) => (
                            <div key={tip.title} className="rounded-lg border border-border p-3 text-left">
                                <div className="mb-2 flex items-center gap-2">
                                    <span className="inline-flex size-5 items-center justify-center rounded-full border border-border text-xs text-secondary">
                                        {index + 1}
                                    </span>
                                    <span className="text-sm font-medium text-primary">{tip.title}</span>
                                </div>
                                <p className="m-0 text-xs text-secondary">{tip.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {isFiltered && onClearFilters && (
                <LemonButton type="secondary" size="small" onClick={onClearFilters}>
                    Clear current filters
                </LemonButton>
            )}
        </div>
    )
}

function getFilterBubbleText(activeFilterTypes?: Props['activeFilterTypes']): string {
    if (!activeFilterTypes) {
        return 'Try adjusting your filters'
    }
    const { dateRange, answerFilters, propertyFilters } = activeFilterTypes
    const activeCount = [dateRange, answerFilters, propertyFilters].filter(Boolean).length
    if (activeCount > 1) {
        return 'Try adjusting your filters'
    }
    if (dateRange) {
        return 'Try a wider date range'
    }
    if (answerFilters) {
        return 'Try different answer choices'
    }
    if (propertyFilters) {
        return 'Try fewer property filters'
    }
    return 'Try adjusting your filters'
}
