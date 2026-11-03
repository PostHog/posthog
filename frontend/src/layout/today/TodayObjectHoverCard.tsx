import { useActions, useValues } from 'kea'
import { Fragment, Suspense, lazy, useEffect, useMemo } from 'react'

import { IconArrowRight, IconChevronRight, IconExternal } from '@posthog/icons'
import { Badge, Item, ItemContent, ItemSeparator, ItemTitle, Skeleton } from '@posthog/quill'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { retryImport } from 'lib/utils/retryImport'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { baseObjectType } from 'scenes/library/libraryUtils'
import { todayNumber } from 'scenes/project-homepage/today/todayNumbers'

import { TodayHoverCardFact } from './TodayHoverCardFact'
import { cardMenuParts } from './todayMenuParts'
import { todayObjectGlanceLogic } from './todayObjectGlanceLogic'

// The charts are most of the code the home page adds, and this card opens only on hover.
const TodaySparkline = lazy(() =>
    retryImport(() =>
        import('scenes/project-homepage/today/TodaySparkline').then((m) => ({ default: m.TodaySparkline }))
    )
)
import { GLANCE_TYPES, TodayObjectGlance } from './todayObjectGlances'
import { TodayObjectIcon } from './TodayObjectIcon'
import { TodayObjectPreview } from './todayPreviewCards'
import { activityDetail } from './todayWorkItems'

function Glance({ glance }: { glance: TodayObjectGlance }): JSX.Element {
    const { headline } = glance
    return (
        <>
            {headline && (
                <div className="flex flex-col gap-1">
                    <div className="flex min-w-0 items-baseline gap-1.5">
                        <span className="text-lg leading-6 font-semibold tabular-nums">{headline.value}</span>
                        <span className="min-w-0 truncate text-xs text-muted-foreground">{headline.caption}</span>
                    </div>
                    {headline.series.length > 1 && (
                        <div className="h-10">
                            <Suspense fallback={null}>
                                <TodaySparkline
                                    values={headline.series}
                                    labels={headline.labels}
                                    tone="neutral"
                                    emphasizeLast={1}
                                    formatValue={headline.formatValue ?? todayNumber}
                                />
                            </Suspense>
                        </div>
                    )}
                </div>
            )}
            {glance.description && (
                <p className="m-0 line-clamp-2 text-xs text-muted-foreground">{glance.description}</p>
            )}
            {glance.facts.map(([label, value]) => (
                <TodayHoverCardFact key={label} label={label}>
                    {value}
                </TodayHoverCardFact>
            ))}
        </>
    )
}

export function TodayObjectHoverCard({
    preview,
    onAction,
}: {
    preview: TodayObjectPreview
    onAction: () => void
}): JSX.Element {
    const { href, ref, type } = preview
    const { glanceFor } = useValues(todayObjectGlanceLogic)
    const { showGlance } = useActions(todayObjectGlanceLogic)
    const glanceRef = ref && GLANCE_TYPES.includes(baseObjectType(type)) ? ref : null
    useEffect(() => {
        if (glanceRef) {
            showGlance(type, glanceRef)
        }
    }, [glanceRef, type, showGlance])
    const glance = glanceRef ? glanceFor(type, glanceRef) : null
    const opened = activityDetail(preview.lastViewedAt)
    const { Item: ActionItem } = useMemo(() => cardMenuParts(onAction), [onAction])
    return (
        <div className="flex flex-col" data-attr="today-object-hover-card">
            <Item size="xs" className="items-start">
                <ItemContent className="min-w-0 gap-2">
                    <ItemTitle className="flex items-center gap-2 wrap-anywhere">
                        <TodayObjectIcon
                            type={type}
                            className="shrink-0 [--icon-stack-size:22px] [--quill-icon-stack-ring:var(--card)]"
                        />
                        <span className="min-w-0 flex-1 font-semibold">{preview.name}</span>
                        {glance?.status && (
                            <Badge variant={glance.status.tone} className="shrink-0">
                                {glance.status.label}
                            </Badge>
                        )}
                    </ItemTitle>
                    <div className="flex flex-col gap-1.5 pl-7.5">
                        <div className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                            {preview.typeLabel && (
                                <span className="shrink-0">{capitalizeFirstLetter(preview.typeLabel)} in</span>
                            )}
                            <span className="flex min-w-0 items-center gap-0.5" title={preview.folder.join(' / ')}>
                                {preview.folder.length === 0 ? (
                                    <span>Project root</span>
                                ) : (
                                    preview.folder.map((segment, index) => (
                                        <Fragment key={index}>
                                            {index > 0 && <IconChevronRight className="size-3 shrink-0" />}
                                            <span
                                                className={
                                                    index === preview.folder.length - 1 ? 'truncate' : 'shrink-0'
                                                }
                                            >
                                                {segment}
                                            </span>
                                        </Fragment>
                                    ))
                                )}
                            </span>
                        </div>
                        {glance === undefined ? (
                            <div className="flex flex-col gap-1.5" aria-busy="true">
                                <Skeleton className="h-4 w-2/3" />
                                <Skeleton className="h-4 w-1/2" />
                            </div>
                        ) : (
                            glance && <Glance glance={glance} />
                        )}
                        {opened && (
                            <TodayHoverCardFact label="Opened">
                                <span title={opened.title}>{opened.text}</span>
                            </TodayHoverCardFact>
                        )}
                    </div>
                </ItemContent>
            </Item>
            {href && (
                <>
                    <ItemSeparator className="my-0" />
                    <div className="flex flex-col p-1">
                        <ActionItem to={href} dataAttr="today-object-card-open">
                            <IconArrowRight />
                            Open
                        </ActionItem>
                        <ActionItem onClick={() => newInternalTab(href)} dataAttr="today-object-card-open-new-tab">
                            <IconExternal />
                            Open in new tab
                        </ActionItem>
                    </div>
                </>
            )}
        </div>
    )
}
