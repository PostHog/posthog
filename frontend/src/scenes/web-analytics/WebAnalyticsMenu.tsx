import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ScenePanel, ScenePanelActionsSection, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'

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
    const { shouldFilterTestAccounts, hiddenTiles, productTab } = useValues(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { setShouldFilterTestAccounts, setTileVisibility } = useActions(webAnalyticsLogic)

    const showTileToggles = featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_TOGGLES]
    const availableTiles = productTab === ProductTab.ANALYTICS ? ANALYTICS_TILES : []

    return (
        <ScenePanel>
            <ScenePanelActionsSection>
                <Link to={urls.sessionAttributionExplorer()} buttonProps={{ menuItem: true }}>
                    <IconSearch /> Session Attribution Explorer
                </Link>
            </ScenePanelActionsSection>
            <ScenePanelDivider />
            <ScenePanelActionsSection>
                <ButtonPrimitive
                    menuItem
                    onClick={() => {
                        setShouldFilterTestAccounts(!shouldFilterTestAccounts)
                    }}
                >
                    <LemonSwitch checked={shouldFilterTestAccounts} size="xsmall" />
                    Filter out internal and test users
                </ButtonPrimitive>
            </ScenePanelActionsSection>
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
