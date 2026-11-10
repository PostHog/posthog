import { useMountedLogic, useValues } from 'kea'

import { IconBell, IconCheckCircle, IconFlask } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { noEventsBannerLogic } from '~/layout/navigation/noEventsBannerLogic'

import { TodayEmptyPanel } from './TodayEmptyPanel'
import { todayGetStartedLogic } from './todayGetStartedLogic'
import { TodaySetupRow } from './TodaySetupRow'

const GHOST_ROWS = [
    { width: 'w-1/2', glyph: <IconBell /> },
    { width: 'w-1/3', glyph: <IconFlask /> },
]

function FirstEventWatcher(): null {
    useMountedLogic(noEventsBannerLogic)
    return null
}

export function TodayForYouEmpty(): JSX.Element {
    const { stepsReady, allDone, hidden, isNewProject } = useValues(todayGetStartedLogic)
    const showGuide = !allDone && !hidden

    if (!stepsReady && !hidden) {
        return <Skeleton className="h-12 w-full" />
    }
    if (isNewProject) {
        return (
            <>
                <FirstEventWatcher />
                {showGuide ? <TodaySetupRow /> : null}
                <TodayEmptyPanel
                    message="Alerts, experiments and other changes that need you show up here."
                    dataAttr="today-for-you-example"
                >
                    <ol className="TodayRows">
                        {GHOST_ROWS.map((row) => (
                            <li key={row.width} className="TodayRow">
                                <IconStack className="TodayRow__icons">
                                    <IconStackItem>{row.glyph}</IconStackItem>
                                </IconStack>
                                <div>
                                    <span className={`TodayEmptyPanel__bar TodayGhostRow__title ${row.width}`} />
                                    <span className="TodayEmptyPanel__bar TodayGhostRow__meta w-1/4" />
                                </div>
                            </li>
                        ))}
                    </ol>
                </TodayEmptyPanel>
            </>
        )
    }
    if (showGuide) {
        return (
            <>
                <TodaySetupRow />
                <Text size="xs" variant="muted" render={<p />} className="m-0">
                    Nothing else needs you today.
                </Text>
            </>
        )
    }
    return (
        <ol className="TodayRows" data-attr="today-for-you-empty">
            <li className="TodayRow">
                <IconStack className="TodayRow__icons">
                    <IconStackItem color="var(--success-foreground)">
                        <IconCheckCircle />
                    </IconStackItem>
                </IconStack>
                <div className="min-w-0">
                    <span className="TodayRow__title">Nothing needs you today</span>
                    <p className="TodayRow__meta">
                        PostHog checks your alerts, experiments, flags and tickets each day.
                    </p>
                </div>
                <div className="TodayRow__end">
                    <Button
                        size="sm"
                        variant="link-muted"
                        render={<LinkPrimitive to={urls.alerts()} />}
                        data-attr="today-for-you-empty-alerts"
                    >
                        Set up alerts
                    </Button>
                </div>
            </li>
        </ol>
    )
}
