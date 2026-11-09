import type { ReactNode } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Text, cn } from '@posthog/quill'

import { TodayNewsFeedback } from './TodayNewsFeedback'
import type { TodayNewsRatedStory } from './todayNewsLogic'

export function TodayNewsCard({
    title,
    rated,
    onDiveIn,
    className,
    children,
}: {
    title: string
    rated: TodayNewsRatedStory
    onDiveIn: () => void
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="relative flex w-full flex-col">
            <button
                type="button"
                onClick={onDiveIn}
                aria-label={`Dive in: ${title}`}
                className="group/story -m-3 flex flex-1 cursor-pointer flex-col gap-3 rounded-lg p-3 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                data-attr="today-news-dive-in"
            >
                <span className={cn('flex flex-col gap-1.5', className)}>{children}</span>
                <Text size="xs" render={<span />} className="mt-auto flex h-6 items-center gap-1 font-medium">
                    Dive in
                    <IconArrowRight className="size-3.5 transition-transform group-hover/story:translate-x-0.5 motion-reduce:transition-none" />
                </Text>
            </button>
            <span className="absolute bottom-0 end-0">
                <TodayNewsFeedback story={rated} />
            </span>
        </div>
    )
}
