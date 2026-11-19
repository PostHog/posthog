import { Collapsible } from '@base-ui/react/collapsible'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useId, useMemo } from 'react'

import { IconChevronDown, IconPinFilled } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { todayObjectGlanceLogic } from '~/layout/today/todayObjectGlanceLogic'
import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'
import { TodayPreviewCardProvider } from '~/layout/today/TodayPreviewCardProvider'
import { objectPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { todayHomeEditLogic } from './todayHomeEditLogic'
import { TodayHomeHeading } from './TodayHomeHeading'
import { TodayJumpBackPinPicker } from './TodayJumpBackPinPicker'
import { RECENT_OBJECT_COUNT, todayLogic } from './todayLogic'
import { JumpBackObject } from './todayRecentObjects'

function RecentObjectRow({
    entry,
    position,
    frequent,
}: {
    entry: JumpBackObject
    position: number
    frequent: boolean
}): JSX.Element {
    const preview = useMemo(() => objectPreview(entry, 'jump_back'), [entry])
    const { jumpBackOpened } = useActions(todayLogic)
    const pinned = entry.jumpBackReason === 'pinned'
    return (
        <li className="TodayJumpRow">
            <TodayObjectIcon type={entry.type} className="TodayJumpRow__icon" />
            <TodayPreviewTrigger payload={preview}>
                <LinkPrimitive
                    to={preview.href ?? undefined}
                    className="TodayJumpRow__link"
                    data-attr="today-home-recent-object"
                    onClick={() => jumpBackOpened(entry, position, frequent)}
                >
                    {preview.name}
                </LinkPrimitive>
                <span className="TodayJumpRow__meta">
                    {pinned && (
                        <>
                            <IconPinFilled className="TodayJumpRow__pinned" aria-hidden />
                            <span className="sr-only">Pinned, </span>
                        </>
                    )}
                    {entry.last_viewed_at ? (
                        <time dateTime={entry.last_viewed_at} title={`Last opened: ${entry.last_viewed_at}`}>
                            <span className="sr-only">Last opened </span>
                            <TZLabel time={entry.last_viewed_at} showPopover={false} noStyles />
                        </time>
                    ) : pinned ? (
                        <span>Not opened yet</span>
                    ) : (
                        <span title="Last-opened time is not available">Time unknown</span>
                    )}
                </span>
            </TodayPreviewTrigger>
        </li>
    )
}

export function TodayRecents(): JSX.Element {
    useMountedLogic(todayObjectGlanceLogic)
    const { recentObjects, frequentObjectsLoading, recentsHasLoaded, listExpanded } = useValues(todayLogic)
    const { setListExpanded } = useActions(todayLogic)
    const { pickPane } = useActions(todayShellLogic)
    const { homeEditing } = useValues(todayHomeEditLogic)
    const titleId = useId()
    const shown = recentObjects.slice(0, RECENT_OBJECT_COUNT)
    const more = recentObjects.slice(RECENT_OBJECT_COUNT)

    return (
        <Collapsible.Root
            open={listExpanded.recents}
            onOpenChange={(open) => setListExpanded('recents', open)}
            render={<section className="TodayHome__list" aria-labelledby={titleId} />}
        >
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Jump back in</TodayHomeHeading>
                {homeEditing && (
                    <TodayJumpBackPinPicker
                        trigger={
                            <Button
                                variant="outline"
                                size="sm"
                                className="-my-1"
                                aria-label="Edit Jump back in"
                                data-attr="today-home-recent-edit"
                            >
                                Edit
                            </Button>
                        }
                    />
                )}
            </div>
            {!recentsHasLoaded || frequentObjectsLoading ? (
                <p className="TodayHome__note">Finding your items…</p>
            ) : recentObjects.length === 0 ? (
                <p className="TodayHome__note">
                    <span>
                        Anything you open, like a dashboard or a feature flag, shows up here. Find things to open
                        in{' '}
                    </span>
                    <button
                        type="button"
                        className="TodayHome__noteLink"
                        data-attr="today-home-recent-library"
                        onClick={() => pickPane('products')}
                    >
                        Products
                    </button>
                    <span>.</span>
                </p>
            ) : (
                <TodayPreviewCardProvider>
                    <ul className="TodayJumpList">
                        {shown.map((entry, index) => (
                            <RecentObjectRow
                                key={entry.id}
                                entry={entry}
                                position={index + 1}
                                frequent={entry.jumpBackReason === 'frequent'}
                            />
                        ))}
                    </ul>
                    {more.length > 0 && (
                        <Collapsible.Panel className="TodayJumpList__more">
                            <ul className="TodayJumpList">
                                {more.map((entry, index) => (
                                    <RecentObjectRow
                                        key={entry.id}
                                        entry={entry}
                                        position={RECENT_OBJECT_COUNT + index + 1}
                                        frequent={entry.jumpBackReason === 'frequent'}
                                    />
                                ))}
                            </ul>
                        </Collapsible.Panel>
                    )}
                    {more.length > 0 && (
                        <div className="TodayRows__footer">
                            <Collapsible.Trigger
                                render={<Button className="TodayRows__more" />}
                                data-attr="today-home-recent-more"
                            >
                                <IconChevronDown
                                    className={
                                        listExpanded.recents ? 'TodayRows__moreIcon rotate-180' : 'TodayRows__moreIcon'
                                    }
                                    aria-hidden
                                />
                                <span>{listExpanded.recents ? 'Show less' : 'Show more'}</span>
                            </Collapsible.Trigger>
                        </div>
                    )}
                </TodayPreviewCardProvider>
            )}
        </Collapsible.Root>
    )
}
