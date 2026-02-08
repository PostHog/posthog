import { useActions, useValues } from 'kea'

import { IconEllipsis, IconSearch } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuSection } from 'lib/lemon-ui/LemonMenu'
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

    const { setShouldFilterTestAccounts, setTileVisibility, resetTileVisibility } = useActions(webAnalyticsLogic)

    const showTileToggles = featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_TOGGLES]
    const availableTiles = productTab === ProductTab.ANALYTICS ? ANALYTICS_TILES : []
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

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
                            label="Filter out internal and test users"
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

    if (isRemovingSidePanelFlag) {
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
                <ScenePanelDivider />
                <ScenePanelActionsSection>
                    <ScenePanelLabel title="Visible tiles" className="px-1.5">
                        {availableTiles.map((tileId) => (
                            <ButtonPrimitive
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
            </ScenePanel>
        )
    }

    return (
        <>
            <LemonMenu items={sections} closeOnClickInside={false}>
                <LemonButton icon={<IconEllipsis />} size="small" />
            </LemonMenu>
        </>
    )
}
