import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBolt, IconGear, IconSearch, IconSparkles, IconStar, IconTarget, IconX } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'

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

function NewQueryEngineTooltipBody(): JSX.Element {
    return (
        <div className="max-w-100 p-1 text-xs">
            <div className="mb-2 flex items-center gap-2">
                <strong>About the new query engine</strong>
                <Badge variant="info" className="uppercase">
                    Beta
                </Badge>
            </div>
            <p className="mb-2">
                Our new web analytics query engine powers faster queries using pre-aggregated data, giving you quicker
                access to insights and it's much better at handling large datasets.
            </p>
            <div className="mb-2">
                <strong>A few things to note:</strong>
                <ul className="list-disc ml-4 mt-1 space-y-1">
                    <li>Some filters may not yet be supported, but we're working on expanding coverage.</li>
                    <li>
                        We use smart approximation techniques to keep performance high, and we aim for less than 1%
                        difference compared to exact results.
                    </li>
                    <li>Results are currently tied to UTC timezone for query and display.</li>
                </ul>
            </div>
            <div>
                <strong>Coming soon:</strong>
                <ul className="list-disc ml-4 mt-1 space-y-1">
                    <li>Use the new engine for chart visualizations</li>
                    <li>Support for channel types in breakdowns</li>
                    <li>Enable conversion goals</li>
                    <li>Further improvements in accuracy</li>
                    <li>More filters!</li>
                </ul>
            </div>
        </div>
    )
}

export function WebAnalyticsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <WebAnalyticsSceneMenuBarInner />
}

function WebAnalyticsSceneMenuBarInner(): JSX.Element {
    const { hasSavedFocusMode, hiddenTiles, isFocusModeActive, productTab, shouldFilterTestAccounts, showFocusMode } =
        useValues(webAnalyticsLogic)
    const { enterFocusMode, exitFocusMode, openFocusModeModal, setShouldFilterTestAccounts, setTileVisibility } =
        useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { currentTeam } = useValues(teamLogic)
    const { achievementsOptOut } = useValues(webAnalyticsAchievementsPreferencesLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { openModal: openAchievementsModal } = useActions(webAnalyticsAchievementsLogic)

    const showAchievements = isWebAnalyticsAchievementsEnabled(featureFlags, achievementsOptOut)
    const showRecap = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_RECAP]
    const showTileToggles = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_TOGGLES]
    const showQueryEngineToggle = !!featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES]
    const isUsingNewEngine = !!currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
    const availableTiles = productTab === ProductTab.ANALYTICS ? ANALYTICS_TILES : []
    const hasFileItems = !!projectTreeRefEntry

    const handleToggleEngine = (checked: boolean): void => {
        updateCurrentTeam({
            modifiers: {
                ...currentTeam?.modifiers,
                useWebAnalyticsPreAggregatedTables: checked,
            },
        })
    }

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="web-analytics-menubar-file" disabled={!hasFileItems}>
                {hasFileItems && <SceneMenuBarFileItems dataAttrKey="web-analytics" />}
            </SceneMenuBarMenu>
            {showQueryEngineToggle && (
                <SceneMenuBarMenu label="Edit" dataAttr="web-analytics-menubar-edit">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <SceneMenuBarCheckboxItem
                                    checked={isUsingNewEngine}
                                    onCheckedChange={handleToggleEngine}
                                    data-attr="web-analytics-menubar-query-engine"
                                >
                                    <IconBolt />
                                    New query engine
                                    <Badge variant="info" className="ml-1 uppercase">
                                        Beta
                                    </Badge>
                                </SceneMenuBarCheckboxItem>
                            }
                        />
                        <TooltipContent>
                            <NewQueryEngineTooltipBody />
                        </TooltipContent>
                    </Tooltip>
                </SceneMenuBarMenu>
            )}
            <SceneMenuBarMenu label="View" dataAttr="web-analytics-menubar-view">
                {showRecap && (
                    <SceneMenuBarItem
                        onClick={() => router.actions.push(urls.webAnalyticsRecap())}
                        data-attr="web-analytics-menubar-weekly-recap"
                    >
                        <IconSparkles />
                        Weekly recap
                    </SceneMenuBarItem>
                )}
                <SceneMenuBarItem
                    onClick={() => window.location.assign(urls.sessionAttributionExplorer())}
                    data-attr="web-analytics-menubar-session-attribution"
                >
                    <IconSearch />
                    Session Attribution Explorer
                </SceneMenuBarItem>
                {showFocusMode && (
                    <SceneMenuBarItem
                        onClick={() => openFocusModeModal()}
                        data-attr="web-analytics-menubar-focus-mode-settings"
                        opensFloatingUi
                    >
                        <IconGear />
                        Focus mode settings
                    </SceneMenuBarItem>
                )}
                {showFocusMode &&
                    (isFocusModeActive ? (
                        <SceneMenuBarItem onClick={exitFocusMode} data-attr="web-analytics-menubar-exit-focus-mode">
                            <IconX />
                            Exit focus mode
                        </SceneMenuBarItem>
                    ) : hasSavedFocusMode ? (
                        <SceneMenuBarItem onClick={enterFocusMode} data-attr="web-analytics-menubar-enter-focus-mode">
                            <IconTarget />
                            Enter focus mode
                        </SceneMenuBarItem>
                    ) : null)}
                {showAchievements && (
                    <SceneMenuBarItem
                        onClick={() => openAchievementsModal()}
                        data-attr="web-analytics-achievements-open"
                        opensFloatingUi
                    >
                        <IconStar />
                        Achievements
                    </SceneMenuBarItem>
                )}
                <SceneMenuBarSeparator />
                <SceneMenuBarCheckboxItem
                    checked={shouldFilterTestAccounts}
                    onCheckedChange={(checked) => setShouldFilterTestAccounts(checked)}
                    data-attr="web-analytics-menubar-filter-test"
                >
                    Filter out internal and test users
                </SceneMenuBarCheckboxItem>
                {showTileToggles && availableTiles.length > 0 && (
                    <SceneMenuBarSubMenu label="Visible tiles">
                        {availableTiles.map((tileId) => (
                            <SceneMenuBarCheckboxItem
                                key={tileId}
                                checked={!hiddenTiles.includes(tileId)}
                                onCheckedChange={(checked) => setTileVisibility(tileId, checked)}
                                data-attr={`web-analytics-menubar-tile-${tileId}`}
                            >
                                {TILE_LABELS[tileId]}
                            </SceneMenuBarCheckboxItem>
                        ))}
                    </SceneMenuBarSubMenu>
                )}
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
