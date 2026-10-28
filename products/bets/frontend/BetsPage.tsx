import './Bets.scss'

import { useValues } from 'kea'
import { router } from 'kea-router'
import { type ReactNode, useLayoutEffect, useRef } from 'react'

import { Text } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'

import { QuillSceneTrail } from '~/layout/scenes/components/QuillSceneTrail'
import { TodayPreviewCardProvider } from '~/layout/today/TodayPreviewCardProvider'
import type { Breadcrumb } from '~/types'

export function BetsPage({
    title,
    titleAddon,
    description,
    actions,
    children,
    breadcrumbs,
}: {
    title: ReactNode
    titleAddon?: ReactNode
    description?: string
    actions?: ReactNode
    children: ReactNode
    breadcrumbs: Breadcrumb[]
}): JSX.Element {
    const { location } = useValues(router)
    const ref = useRef<HTMLDivElement>(null)
    useLayoutEffect(() => {
        ref.current?.closest('main')?.scrollTo({ top: 0 })
    }, [location.pathname])
    return (
        <div ref={ref} className="Today Bets flex-1 min-h-full">
            <div className="TodayHome Today__page Bets__wide" data-quill>
                <nav
                    aria-label="Breadcrumb"
                    className="-ms-2 mb-5 flex flex-wrap items-center gap-2 min-w-0 [&>a]:!ms-0 [&>a]:!me-0 [&>span]:!ms-0 [&>span]:!me-0"
                >
                    {breadcrumbs.slice(0, -1).map((crumb) => (
                        <QuillSceneTrail key={String(crumb.key)} parent={{ name: crumb.name, path: crumb.path }} />
                    ))}
                    <Text size="xs" className="truncate min-w-0" render={<span aria-current="page" />}>
                        {breadcrumbs.at(-1)?.name}
                    </Text>
                </nav>
                <header className="Bets__heading flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
                            <Text render={<h1 />} className="m-0 text-[21px] font-[560] tracking-[-0.015em]">
                                {title}
                            </Text>
                            {titleAddon}
                        </div>
                        {description && (
                            <Text size="sm" variant="muted" render={<p className="mt-2 mb-0" />}>
                                {description}
                            </Text>
                        )}
                    </div>
                    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
                </header>
                <TodayPreviewCardProvider>
                    <div className="TodayHome__body @container/bets">{children}</div>
                </TodayPreviewCardProvider>
            </div>
        </div>
    )
}
