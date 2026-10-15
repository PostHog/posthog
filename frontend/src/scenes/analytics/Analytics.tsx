import { useActions, useValues } from 'kea'
import { useId, useMemo } from 'react'

import { Button, Heading, IconStack, IconStackItem } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { TodayHomeHeading } from 'scenes/project-homepage/today/TodayHomeHeading'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'
import { TodayPreviewCardProvider } from '~/layout/today/TodayPreviewCardProvider'
import { objectPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { withBackLink } from './analyticsBackLink'
import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { analyticsHomeLogic } from './analyticsHomeLogic'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES } from './analyticsUtils'
import { newAnalyticsLogic } from './newAnalyticsLogic'
import { NewAnalyticsMenu } from './NewAnalyticsMenu'

export const scene: SceneExport = {
    component: Analytics,
    logic: analyticsHomeLogic,
}

export function Analytics(): JSX.Element {
    const analyticsEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    // The page ships behind the Today navigation, so without the flag `/analytics` stays a missing page.
    return analyticsEnabled ? <AnalyticsContent /> : <NotFound object="page" />
}

function CreateSection(): JSX.Element {
    const { pickNewAnalyticsType } = useActions(newAnalyticsLogic)

    return (
        <section aria-label="Create something new" className="flex flex-col gap-3">
            <Heading render={<h2 />} size="sm" className="m-0">
                <NewAnalyticsMenu
                    source="home"
                    trigger={
                        <Button
                            variant="link"
                            size="sm"
                            className="h-auto p-0 text-base font-semibold text-foreground"
                            data-attr="analytics-home-create-heading"
                        />
                    }
                >
                    Create something new
                </NewAnalyticsMenu>
            </Heading>
            <div className="grid grid-cols-2 gap-3 @3xl/analytics:grid-cols-4">
                {ANALYTICS_TYPES.map((info) => (
                    <button
                        key={info.type}
                        type="button"
                        className="flex min-h-36 cursor-pointer flex-col items-start gap-3 rounded-lg border border-border bg-surface-primary p-4 text-start text-foreground transition-colors hover:border-border-bold hover:bg-fill-button-tertiary-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        onClick={() => pickNewAnalyticsType(info.type, 'home')}
                        data-attr={`analytics-home-new-${info.type}`}
                    >
                        <IconStack className="[&_svg]:size-5">
                            <IconStackItem color={info.color}>
                                <AnalyticsTypeIcon type={info.type} />
                            </IconStackItem>
                        </IconStack>
                        <span className="flex min-w-0 flex-col gap-1">
                            <span className="text-sm font-semibold">{info.label}</span>
                            <span className="text-xs text-muted-foreground">{info.description}</span>
                        </span>
                    </button>
                ))}
            </div>
        </section>
    )
}

function JumpRow({ entry }: { entry: FileSystemEntry }): JSX.Element {
    const preview = useMemo(() => objectPreview(entry), [entry])
    return (
        <li className="TodayJumpRow">
            <TodayObjectIcon type={entry.type} className="TodayJumpRow__icon" />
            <TodayPreviewTrigger payload={preview}>
                <LinkPrimitive
                    to={preview.href ? withBackLink(preview.href) : undefined}
                    className="TodayJumpRow__link"
                    data-attr="analytics-home-recent-row"
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

/** The eight most recently opened items, laid out like the home page's Jump back in. */
function JumpBackInSection(): JSX.Element {
    const { recentJumpEntries, recentEntries, recentEntriesLoading, recentsFailed } = useValues(analyticsHomeLogic)
    const { loadRecentEntries } = useActions(analyticsHomeLogic)
    const titleId = useId()

    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Jump back in</TodayHomeHeading>
                <LinkPrimitive
                    to={urls.analyticsList()}
                    className="TodayHome__headingLink"
                    data-attr="analytics-home-recent-see-all"
                >
                    See all
                </LinkPrimitive>
            </div>
            {recentEntries === null && recentEntriesLoading ? (
                <p className="TodayHome__note">Finding what you looked at last…</p>
            ) : recentEntries === null || (recentsFailed && recentJumpEntries.length === 0) ? (
                <p className="TodayHome__note">
                    <span>Couldn’t load what you opened recently. </span>
                    <button
                        type="button"
                        className="TodayHome__noteLink"
                        onClick={() => loadRecentEntries()}
                        data-attr="analytics-home-recent-retry"
                    >
                        Try again
                    </button>
                </p>
            ) : recentJumpEntries.length === 0 ? (
                <p className="TodayHome__note">Anything you open, like a dashboard or an insight, shows up here.</p>
            ) : (
                <TodayPreviewCardProvider>
                    <ul className="TodayJumpList">
                        {recentJumpEntries.map((entry) => (
                            <JumpRow key={entry.id} entry={entry} />
                        ))}
                    </ul>
                </TodayPreviewCardProvider>
            )}
        </section>
    )
}

function AnalyticsContent(): JSX.Element {
    return (
        <SceneContent>
            <div data-quill className="@container/analytics mx-auto flex w-full max-w-5xl flex-col gap-8 py-4">
                <CreateSection />
                <JumpBackInSection />
            </div>
            <AnalyticsCreateModals />
        </SceneContent>
    )
}
