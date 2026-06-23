import clsx from 'clsx'
import { useValues } from 'kea'

import { IconArrowRight, IconClock, IconInfo, IconPin, IconStar } from '@posthog/icons'

import { PostHogLogo } from 'lib/brand/v2'

import { onboardingLogic } from '../../onboardingLogic'
import { type HomeListItem } from '../types'

const SKELETON_WIDTHS = ['w-24', 'w-20', 'w-28', 'w-16', 'w-24']

function SkeletonRow({ variant, index }: { variant: 'square' | 'dot'; index: number }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span
                className={clsx(
                    'size-3 shrink-0 bg-fill-highlight-100',
                    variant === 'dot' ? 'rounded-full bg-accent' : 'rounded-sm'
                )}
            />
            <span
                className={clsx(
                    'h-2 rounded-full bg-fill-highlight-100',
                    SKELETON_WIDTHS[index % SKELETON_WIDTHS.length]
                )}
            />
        </div>
    )
}

function HomeColumn({
    title,
    icon,
    items,
    variant,
    emptyLabel,
}: {
    title: string
    icon: JSX.Element
    items: HomeListItem[]
    variant: 'square' | 'dot'
    emptyLabel?: string
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-2.5">
            <div className="flex items-center gap-1.5 text-xxs font-semibold text-secondary uppercase tracking-wide">
                <span className="size-3 text-tertiary">{icon}</span>
                {title}
            </div>
            {items.length > 0 ? (
                <div className="flex flex-col gap-2.5">
                    {items.map((_, i) => (
                        <SkeletonRow key={i} variant={variant} index={i} />
                    ))}
                </div>
            ) : (
                <div className="flex items-center gap-1.5 rounded-md border border-dashed border-primary px-2 py-2 text-xs text-muted">
                    {emptyLabel ?? 'Nothing yet'}
                    <IconInfo className="size-3" />
                </div>
            )}
        </div>
    )
}

export function HomePage({
    greetingName,
    pinnedDashboards,
    recents,
    starred,
}: {
    greetingName: string
    pinnedDashboards: HomeListItem[]
    recents: HomeListItem[]
    starred: HomeListItem[]
}): JSX.Element {
    const { previewFocus } = useValues(onboardingLogic)

    return (
        <div className="flex h-full flex-col items-start justify-start pl-2 pt-6">
            <PostHogLogo wordmark={false} className="mb-3 h-8 w-auto" />
            <h1
                className={clsx(
                    'mb-5 text-xl font-bold text-default rounded',
                    previewFocus === 'userName' &&
                        'px-2 py-1 -mx-2 -my-1 ring ring-yellow-500 ring-offset-1 ring-offset-transparent shadow-[0_0_0_4px_rgba(251,146,60,0.35),0_0_24px_6px_rgba(249,115,22,0.2)] transition-all duration-150'
                )}
            >
                Hello, {greetingName.trim() ? greetingName : <span className="text-muted">your name</span>}
            </h1>
            <div className="flex w-full max-w-xl items-center gap-2 rounded-lg border border-primary bg-surface-primary px-3 py-2.5">
                <span className="flex-1 truncate text-sm text-muted">
                    What can I help you with? <span className="text-tertiary">/ for commands</span>
                </span>
                <span className="text-xxs text-muted">Tab to search</span>
                <IconArrowRight className="size-4 text-muted" />
            </div>
            <div className="mt-6 grid w-full max-w-xl grid-cols-3 gap-6">
                <HomeColumn title="Pinned dashboards" icon={<IconPin />} items={pinnedDashboards} variant="square" />
                <HomeColumn title="Recents" icon={<IconClock />} items={recents} variant="dot" />
                <HomeColumn
                    title="Starred"
                    icon={<IconStar />}
                    items={starred}
                    variant="dot"
                    emptyLabel="No starred items"
                />
            </div>
        </div>
    )
}
