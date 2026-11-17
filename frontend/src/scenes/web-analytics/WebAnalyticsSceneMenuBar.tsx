import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import {
    IconBolt,
    IconDownload,
    IconGear,
    IconPulse,
    IconSearch,
    IconSparkles,
    IconStar,
    IconTarget,
    IconX,
} from '@posthog/icons'

import { LiveUserCount } from 'lib/components/LiveUserCount'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconLink } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { isWebAnalyticsAchievementsEnabled } from './achievements/gating'
import { webAnalyticsAchievementsLogic } from './achievements/webAnalyticsAchievementsLogic'
import { webAnalyticsAchievementsPreferencesLogic } from './achievements/webAnalyticsAchievementsPreferencesLogic'
import { PRECOMPUTE_TOGGLE_DESCRIPTION, ProductTab, TILE_LABELS, TileId } from './common'
import { shareNudgeLogic } from './shareNudgeLogic'
import { exportAllTilesAsCsvZip } from './webAnalyticsExportUtils'

const RESOURCE_TYPE = 'web-analytics'

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

const LIVE_USER_COUNT_DOC_LINK =
    'https://posthog.com/docs/web-analytics/faq#i-am-online-but-the-online-user-count-is-not-reflecting-my-user'

export function WebAnalyticsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <WebAnalyticsSceneMenuBarInner />
}

function WebAnalyticsSceneMenuBarInner(): JSX.Element {
    const {
        exportAllDisabledReason,
        hasSavedFocusMode,
        hiddenTiles,
        isFocusModeActive,
        isPrecomputeAllowed,
        productTab,
        shouldFilterTestAccounts,
        showFocusMode,
        tiles,
        webQueryModifiers,
    } = useValues(webAnalyticsLogic)
    const {
        enterFocusMode,
        exitFocusMode,
        openFocusModeModal,
        setShouldFilterTestAccounts,
        setTileVisibility,
        setUseWebAnalyticsPrecompute,
        setWebQueryModifiers,
    } = useActions(webAnalyticsLogic)
    const { exportTriggered } = useActions(shareNudgeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { achievementsOptOut } = useValues(webAnalyticsAchievementsPreferencesLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { openModal: openAchievementsModal } = useActions(webAnalyticsAchievementsLogic)
    const fileActions = useSceneFileActions(RESOURCE_TYPE)

    const showAchievements = isWebAnalyticsAchievementsEnabled(featureFlags, achievementsOptOut)
    const showRecap = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_RECAP]
    const showTileToggles = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_TOGGLES]
    const showQueryEngineToggle = !!featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES]
    const filtersV2 =
        !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] || !!featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]
    const isUsingNewEngine = !!currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
    const availableTiles = productTab === ProductTab.ANALYTICS ? ANALYTICS_TILES : []

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'export',
            id: `${RESOURCE_TYPE}-menubar-export-all-csv`,
            label: 'Export all as CSV (.zip)',
            icon: <IconDownload />,
            disabledReason: exportAllDisabledReason ?? undefined,
            onSelect: () => {
                if (exportAllTilesAsCsvZip(tiles)) {
                    exportTriggered()
                }
            },
        },
        ...(!filtersV2
            ? ([
                  {
                      group: 'file',
                      section: 'export',
                      id: `${RESOURCE_TYPE}-menubar-share`,
                      label: 'Share',
                      keywords: ['copy link'],
                      icon: <IconLink />,
                      onSelect: () => {
                          void copyToClipboard(window.location.href, 'link')
                          posthog.capture('web analytics share link copied', { source: 'header_button' })
                      },
                      pinned: { order: 2, variant: 'icon', dataAttr: 'web-analytics-share-button' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...fileActions,
        ...(showQueryEngineToggle
            ? ([
                  {
                      group: 'edit',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-query-engine`,
                      label: 'New query engine',
                      keywords: ['beta', 'pre-aggregated'],
                      icon: <IconBolt />,
                      tooltip: 'Beta. Faster queries from pre-aggregated data, with results in UTC.',
                      checked: isUsingNewEngine,
                      onCheckedChange: (checked) =>
                          updateCurrentTeam({
                              modifiers: { ...currentTeam?.modifiers, useWebAnalyticsPreAggregatedTables: checked },
                          }),
                      pinned: { order: 4, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showRecap
            ? ([
                  {
                      group: 'view',
                      section: 'navigate',
                      id: `${RESOURCE_TYPE}-menubar-weekly-recap`,
                      label: 'Weekly recap',
                      icon: <IconSparkles />,
                      onSelect: () => router.actions.push(urls.webAnalyticsRecap()),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            section: 'navigate',
            id: `${RESOURCE_TYPE}-menubar-session-attribution`,
            label: 'Session Attribution Explorer',
            icon: <IconSearch />,
            onSelect: () => window.location.assign(urls.sessionAttributionExplorer()),
        },
        ...(showFocusMode
            ? ([
                  {
                      group: 'view',
                      section: 'navigate',
                      id: `${RESOURCE_TYPE}-menubar-focus-mode-settings`,
                      label: 'Focus mode settings',
                      icon: <IconGear />,
                      opensFloatingUi: true,
                      onSelect: () => openFocusModeModal(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showFocusMode && isFocusModeActive
            ? ([
                  {
                      group: 'view',
                      section: 'navigate',
                      id: `${RESOURCE_TYPE}-menubar-exit-focus-mode`,
                      label: 'Exit focus mode',
                      icon: <IconX />,
                      onSelect: exitFocusMode,
                  },
              ] satisfies SceneAction[])
            : showFocusMode && hasSavedFocusMode
              ? ([
                    {
                        group: 'view',
                        section: 'navigate',
                        id: `${RESOURCE_TYPE}-menubar-enter-focus-mode`,
                        label: 'Enter focus mode',
                        icon: <IconTarget />,
                        onSelect: enterFocusMode,
                    },
                ] satisfies SceneAction[])
              : []),
        ...(showAchievements
            ? ([
                  {
                      group: 'view',
                      section: 'navigate',
                      id: 'web-analytics-achievements-open',
                      label: 'Achievements',
                      icon: <IconStar />,
                      opensFloatingUi: true,
                      onSelect: () => openAchievementsModal(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(filtersV2
            ? ([
                  {
                      group: 'view',
                      section: 'navigate',
                      type: 'panel',
                      id: `${RESOURCE_TYPE}-menubar-live-users`,
                      label: 'Live users',
                      icon: <IconPulse />,
                      render: () => (
                          <LiveUserCount docLink={LIVE_USER_COUNT_DOC_LINK} dataAttr="web-analytics-live-user-count" />
                      ),
                      pinned: {
                          order: 1,
                          variant: 'icon',
                          render: () => (
                              <LiveUserCount
                                  docLink={LIVE_USER_COUNT_DOC_LINK}
                                  dataAttr="web-analytics-live-user-count"
                              />
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            section: 'toggles',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-filter-test`,
            label: 'Filter test accounts',
            tooltip: 'Filter out internal and test users',
            checked: shouldFilterTestAccounts,
            onCheckedChange: (checked) => setShouldFilterTestAccounts(checked),
            pinned: { order: 3, variant: 'secondary', dataAttr: 'web-analytics-filter-test-accounts' },
        },
        ...(featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PRECOMPUTE_TOGGLE]
            ? ([
                  {
                      group: 'view',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-allow-precompute`,
                      label: 'Allow precompute',
                      tooltip: PRECOMPUTE_TOGGLE_DESCRIPTION,
                      checked: isPrecomputeAllowed,
                      onCheckedChange: (checked) => setUseWebAnalyticsPrecompute(checked),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_QUERY_MODIFIERS]
            ? ([
                  {
                      group: 'view',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-dimensional-tables`,
                      label: 'Use dimensional tables',
                      checked: !!webQueryModifiers.useDimensionalTables,
                      onCheckedChange: (checked) =>
                          setWebQueryModifiers({ useDimensionalTables: checked || undefined }),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showTileToggles && availableTiles.length > 0
            ? ([
                  {
                      group: 'view',
                      section: 'toggles',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-visible-tiles`,
                      label: 'Visible tiles',
                      display: 'submenu',
                      items: availableTiles.map((tileId) => ({
                          type: 'checkbox' as const,
                          id: `${RESOURCE_TYPE}-menubar-tile-${tileId}`,
                          label: TILE_LABELS[tileId],
                          checked: !hiddenTiles.includes(tileId),
                          onCheckedChange: (checked: boolean) => setTileVisibility(tileId, checked),
                      })),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
