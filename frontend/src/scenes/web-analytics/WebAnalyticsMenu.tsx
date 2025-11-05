import { useActions, useValues } from 'kea'

import { IconEllipsis, IconSearch } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuSection } from 'lib/lemon-ui/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

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

    const { setShouldFilterTestAccounts, setTileVisibility, resetTileVisibility } = useActions(webAnalyticsLogic)

    const showTileToggles = featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_TOGGLES]

    const availableTiles = productTab === ProductTab.ANALYTICS ? ANALYTICS_TILES : []

    const sections: LemonMenuSection[] = [
        {
            items: [
                {
                    label: 'Session Attribution Explorer',
                    to: urls.sessionAttributionExplorer(),
                    icon: <IconSearch />,
                },
            ],
        },
        {
            items: [
                {
                    label: () => (
                        <LemonSwitch
                            checked={shouldFilterTestAccounts}
                            onChange={() => {
                                setShouldFilterTestAccounts(!shouldFilterTestAccounts)
                            }}
                            fullWidth={true}
                            label="Filter test accounts"
                        />
                    ),
                },
            ],
        },
    ]

    if (showTileToggles && availableTiles.length > 0) {
        sections.push({
            title: 'Visible tiles',
            items: availableTiles.map((tileId) => ({
                label: () => (
                    <LemonSwitch
                        checked={!hiddenTiles.includes(tileId)}
                        onChange={() => {
                            setTileVisibility(tileId, hiddenTiles.includes(tileId))
                        }}
                        fullWidth={true}
                        label={TILE_LABELS[tileId]}
                    />
                ),
            })),
        })

        if (hiddenTiles.length > 0) {
            sections.push({
                items: [
                    {
                        label: 'Reset to defaults',
                        onClick: resetTileVisibility,
                    },
                ],
            })
        }
    }

    return (
        <LemonMenu items={sections} closeOnClickInside={false}>
            <LemonButton icon={<IconEllipsis />} size="small" />
        </LemonMenu>
    )
}
