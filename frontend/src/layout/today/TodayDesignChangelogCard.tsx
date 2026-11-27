import { useActions, useValues } from 'kea'

import { Button, Card, Text } from '@posthog/quill'

import { todayDesignChangelogLogic } from './todayDesignChangelogLogic'
import { TODAY_RAIL_WIDTH } from './todayShellLogic'
import { centerOf } from './todayTourGeometry'
import { todayTourLogic } from './todayTourLogic'

/** A card at the foot of the rail that says what changed in the beta design, shown to each person once. */
export function TodayDesignChangelogCard(): JSX.Element | null {
    const { changelogShown } = useValues(todayDesignChangelogLogic)
    const { dismissChangelog, showMe } = useActions(todayDesignChangelogLogic)
    const { tourActive } = useValues(todayTourLogic)

    if (!changelogShown || tourActive) {
        return null
    }

    return (
        <Card
            size="sm"
            role="status"
            className="fixed bottom-3 z-[var(--z-popover)] w-72 border border-border shadow-lg"
            // Its left edge sits against the rail, so the card reads as part of the navigation it talks about.
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: TODAY_RAIL_WIDTH + 8 }}
            data-attr="today-design-changelog"
        >
            <div className="flex flex-col gap-1 px-3">
                <Text size="sm" weight="semibold" render={<h2 />} className="m-0">
                    👋 Beta design update
                </Text>
                <Text size="xs" variant="muted" className="m-0">
                    You can now show and hide areas of the navigation in More.
                </Text>
            </div>
            <div className="flex justify-end gap-2 px-3">
                <Button variant="outline" size="sm" onClick={dismissChangelog}>
                    Dismiss
                </Button>
                <Button variant="primary" size="sm" onClick={(event) => showMe(centerOf(event.currentTarget))}>
                    Show me
                </Button>
            </div>
        </Card>
    )
}
