import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodayNotificationsRailTile } from 'products/notifications/frontend/pane/TodayNotificationsRailTile'

import { TodayAccountMenu } from './TodayAccountMenu'
import { TodayMoreMenu } from './TodayMoreMenu'
import { TODAY_PANES, TODAY_RAIL_FOOTER_PANES, TODAY_RAIL_PANES } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, TodayRailPane, railPaneHref, todayShellLogic } from './todayShellLogic'

// pinned: autocapture data-attr. The Settings tile kept the attribute of the gear button it replaced.
const RAIL_DATA_ATTRS: Partial<Record<TodayRailPane, string>> = { settings: 'today-settings' }

export function TodayRail(): JSX.Element {
    const { activePane, effectivePhaiView } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const renderTile = (pane: TodayRailPane): JSX.Element => (
        <TodayRailTile
            key={pane}
            label={TODAY_PANES[pane].label}
            icon={TODAY_PANES[pane].icon}
            active={activePane === pane}
            to={railPaneHref(pane, effectivePhaiView)}
            onClick={() => clickRailPane(pane)}
            dataAttr={RAIL_DATA_ATTRS[pane] ?? `today-rail-${pane}`}
        />
    )

    return (
        <nav
            aria-label="Main"
            className="TodayShell__rail flex shrink-0 flex-col items-center gap-3 bg-[var(--chrome)] pt-3 pb-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            {TODAY_RAIL_PANES.map(renderTile)}
            <div className="mt-auto flex w-full flex-col items-center gap-3">
                {featureFlags[FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS] && (
                    <TodayNotificationsRailTile
                        active={activePane === 'notifications'}
                        onClick={() => clickRailPane('notifications')}
                    />
                )}
                <TodayMoreMenu />
                {TODAY_RAIL_FOOTER_PANES.map(renderTile)}
            </div>
            <TodayAccountMenu />
        </nav>
    )
}
