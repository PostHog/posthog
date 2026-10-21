import { Collapsible } from '@base-ui/react/collapsible'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useId, useMemo } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { todayObjectGlanceLogic } from '~/layout/today/todayObjectGlanceLogic'
import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'
import { TodayPreviewCardProvider } from '~/layout/today/TodayPreviewCardProvider'
import { objectPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { TodayHomeHeading } from './TodayHomeHeading'
import { RECENT_OBJECT_COUNT, todayLogic } from './todayLogic'

function RecentObjectRow({ entry }: { entry: FileSystemEntry }): JSX.Element {
    const preview = useMemo(() => objectPreview(entry), [entry])
    return (
        <li className="TodayJumpRow">
            <TodayObjectIcon type={entry.type} className="TodayJumpRow__icon" />
            <TodayPreviewTrigger payload={preview}>
                <LinkPrimitive
                    to={preview.href ?? undefined}
                    className="TodayJumpRow__link"
                    data-attr="today-home-recent-object"
                >
                    {preview.name}
                </LinkPrimitive>
                {preview.typeLabel && (
                    <span className="TodayJumpRow__meta">{capitalizeFirstLetter(preview.typeLabel)}</span>
                )}
            </TodayPreviewTrigger>
        </li>
    )
}

export function TodayRecents(): JSX.Element {
    useMountedLogic(todayObjectGlanceLogic)
    const { recentObjects, recentsHasLoaded, listExpanded } = useValues(todayLogic)
    const { setListExpanded } = useActions(todayLogic)
    const { pickPane } = useActions(todayShellLogic)
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
                {recentsHasLoaded && more.length > 0 && (
                    <Collapsible.Trigger className="TodayHome__headingLink" data-attr="today-home-recent-more">
                        <span>{listExpanded.recents ? 'Less' : 'More'}</span>
                        <IconChevronDown className="TodayHome__headingChevron size-3" aria-hidden />
                    </Collapsible.Trigger>
                )}
            </div>
            {!recentsHasLoaded ? (
                <p className="TodayHome__note">Finding what you looked at last…</p>
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
                        {shown.map((entry) => (
                            <RecentObjectRow key={entry.id} entry={entry} />
                        ))}
                    </ul>
                    {more.length > 0 && (
                        <Collapsible.Panel className="TodayJumpList__more">
                            <ul className="TodayJumpList">
                                {more.map((entry) => (
                                    <RecentObjectRow key={entry.id} entry={entry} />
                                ))}
                            </ul>
                        </Collapsible.Panel>
                    )}
                </TodayPreviewCardProvider>
            )}
        </Collapsible.Root>
    )
}
