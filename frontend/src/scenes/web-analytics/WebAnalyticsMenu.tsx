import { useActions, useValues } from 'kea'

import { IconGear, IconSearch, IconStar, IconTarget, IconX } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ScenePanel, ScenePanelActionsSection, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { isWebAnalyticsAchievementsEnabled } from './achievements/gating'
import { webAnalyticsAchievementsLogic } from './achievements/webAnalyticsAchievementsLogic'
import { webAnalyticsAchievementsPreferencesLogic } from './achievements/webAnalyticsAchievementsPreferencesLogic'
import { ProductTab, TILE_LABELS, TileId } from './common'

const ANALYTICS_TILES = [
    TileId.OVERVIEW,
    TileId.GRAPHS,
    TileId.PATHS,
    TileId.SOURCES,
    TileId.DEVICES,
    TileId.GEOGRAPHY,
    TileId.ACTIVE_HOURS,
    TileId.RETENTION,
    TileId.GOALS,
    TileId.REPLAY,
    TileId.ERROR_TRACKING,
    TileId.FRUSTRATING_PAGES,
]

export const WebAnalyticsMenu = (): JSX.Element => {
    const { hasSavedFocusMode, hiddenTiles, isFocusModeActive, productTab, showFocusMode, useWebAnalyticsPrecompute } =
        useValues(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { achievementsOptOut } = useValues(webAnalyticsAchievementsPreferencesLogic)

    const { enterFocusMode, exitFocusMode, openFocusModeModal, setUseWebAnalyticsPrecompute, setTileVisibility } =
        useActions(webAnalyticsLogic)
    const { openModal: openAchievementsModal } = useActions(webAnalyticsAchievementsLogic)

    const showTileToggles = featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_TOGGLES]
    const showAchievements = isWebAnalyticsAchievementsEnabled(featureFlags, achievementsOptOut)
    const availableTiles = productTab === ProductTab.ANALYTICS ? ANALYTICS_TILES : []

    return (
        <ScenePanel>
            <ScenePanelActionsSection>
                <Link to={urls.sessionAttributionExplorer()} buttonProps={{ menuItem: true }}>
                    <IconSearch /> Session Attribution Explorer
                </Link>
                {showFocusMode && (
                    <ButtonPrimitive menuItem onClick={() => openFocusModeModal()}>
                        <IconGear />
                        Focus mode settings...
                    </ButtonPrimitive>
                )}
                {showFocusMode &&
                    (isFocusModeActive ? (
                        <ButtonPrimitive menuItem onClick={exitFocusMode}>
                            <IconX />
                            Exit focus mode
                        </ButtonPrimitive>
                    ) : hasSavedFocusMode ? (
                        <ButtonPrimitive menuItem onClick={enterFocusMode}>
                            <IconTarget />
                            Enter focus mode
                        </ButtonPrimitive>
                    ) : null)}
                {showAchievements && (
                    <ButtonPrimitive menuItem onClick={() => openAchievementsModal()}>
                        <IconStar />
                        Achievements
                    </ButtonPrimitive>
                )}
            </ScenePanelActionsSection>
            {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PRECOMPUTE_TOGGLE] && (
                <>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
                        <Tooltip title="When on, eligible web analytics tiles load from a pre-computed result instead of running a live query. Results are faster but may be a few minutes behind the latest events. Other tiles run live as usual.">
                            <ButtonPrimitive
                                menuItem
                                onClick={() => {
                                    // `null` (untouched) is treated as on, so toggling off opts out explicitly.
                                    setUseWebAnalyticsPrecompute(!(useWebAnalyticsPrecompute ?? true))
                                }}
                            >
                                <LemonSwitch checked={useWebAnalyticsPrecompute ?? true} size="xsmall" />
                                Allow precompute
                            </ButtonPrimitive>
                        </Tooltip>
                    </ScenePanelActionsSection>
                </>
            )}
            {showTileToggles && availableTiles.length > 0 && (
                <>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
                        <ScenePanelLabel title="Visible tiles" className="px-1.5">
                            {availableTiles.map((tileId) => (
                                <ButtonPrimitive
                                    key={tileId}
                                    menuItem
                                    onClick={() => {
                                        setTileVisibility(tileId, hiddenTiles.includes(tileId))
                                    }}
                                >
                                    <LemonSwitch checked={!hiddenTiles.includes(tileId)} size="xsmall" />
                                    {TILE_LABELS[tileId]}
                                </ButtonPrimitive>
                            ))}
                        </ScenePanelLabel>
                    </ScenePanelActionsSection>
                </>
            )}
        </ScenePanel>
    )
}
