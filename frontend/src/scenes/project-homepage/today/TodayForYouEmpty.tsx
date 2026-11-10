import { useValues } from 'kea'

import { IconBell, IconFlask } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todayGetStartedLogic } from './todayGetStartedLogic'
import { WATCHED_PRODUCT_ICONS } from './todayRowIcons'
import { TodaySetupRow } from './TodaySetupRow'

const GHOST_ROWS = [
    { width: 'w-3/5', glyph: <IconBell /> },
    { width: 'w-2/5', glyph: <IconFlask /> },
]

export function TodayForYouEmpty(): JSX.Element {
    const { stepsReady, allDone, hidden, isNewProject } = useValues(todayGetStartedLogic)

    if (!stepsReady && !hidden) {
        return <Skeleton className="h-12 w-full" />
    }
    if (!allDone && !hidden) {
        return (
            <>
                <TodaySetupRow />
                {isNewProject ? (
                    <>
                        <ol className="TodayRows TodayRows--ghost" aria-hidden>
                            {GHOST_ROWS.map((row) => (
                                <li key={row.width} className="TodayRow">
                                    <IconStack className="TodayRow__icons">
                                        <IconStackItem>{row.glyph}</IconStackItem>
                                    </IconStack>
                                    <div>
                                        <span className={`TodayGhostRow__line ${row.width}`} />
                                        <span className="TodayGhostRow__line TodayGhostRow__line--meta w-1/4" />
                                    </div>
                                </li>
                            ))}
                        </ol>
                        <Text size="xs" variant="muted" render={<p />} className="m-0">
                            Alerts, experiments, flags and other changes that need you show up here.
                        </Text>
                    </>
                ) : (
                    <Text size="xs" variant="muted" render={<p />} className="m-0">
                        Nothing else needs you today.
                    </Text>
                )}
            </>
        )
    }
    return (
        <Empty className="TodayEmpty" data-attr="today-for-you-empty">
            <EmptyHeader>
                <IconStack>
                    {WATCHED_PRODUCT_ICONS.map((icon, index) => (
                        <IconStackItem key={index} color={icon.color}>
                            {icon.glyph}
                        </IconStackItem>
                    ))}
                </IconStack>
                <EmptyTitle>Nothing needs you today</EmptyTitle>
                <EmptyDescription>
                    Each day, PostHog checks your alerts, experiments, feature flags, workflows, support tickets and
                    recordings. When something changes that needs you, it shows up here.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    size="sm"
                    variant="outline"
                    render={<LinkPrimitive to={urls.alerts()} />}
                    data-attr="today-for-you-empty-alerts"
                >
                    Set up alerts
                </Button>
            </EmptyContent>
        </Empty>
    )
}
