import { useActions, useValues } from 'kea'

import { IconCalendar, IconCheck, IconClock, IconGridMasonry, IconPlus, IconTrash, IconX } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import type { IntervalType } from '~/types'

import { addCrossProjectTileLogic } from './addCrossProjectTileLogic'
import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'
import { QuillCrossProjectDashboardLayoutActions } from './QuillCrossProjectDashboardLayoutActions'

const RESOURCE_TYPE = 'cross-project-dashboard'

const DEFAULT_INTERVAL = 'default'
const INTERVAL_OPTIONS: { value: string; label: string }[] = [
    { value: DEFAULT_INTERVAL, label: 'Default interval' },
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
]

export function CrossProjectDashboardSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <CrossProjectDashboardSceneMenuBarInner />
}

function CrossProjectDashboardSceneMenuBarInner(): JSX.Element {
    const { dashboard, dashboardFilters, layoutEditMode, tiles, dashboardLoading } =
        useValues(crossProjectDashboardLogic)
    const { setDates, setInterval, deleteDashboard, enterLayoutEdit, cancelLayoutEdit, saveLayout } =
        useActions(crossProjectDashboardLogic)
    const { requestOpenModal } = useActions(addCrossProjectTileLogic({ dashboardId: dashboard?.id ?? '' }))
    const layoutPin = {
        order: 0,
        variant: 'secondary',
        render: () => <QuillCrossProjectDashboardLayoutActions />,
    } as const

    const actions: SceneAction[] = dashboard
        ? [
              {
                  group: 'file',
                  section: 'create',
                  id: `${RESOURCE_TYPE}-menubar-add-insight`,
                  label: 'Add insight',
                  icon: <IconPlus />,
                  opensFloatingUi: true,
                  onSelect: () => requestOpenModal(),
                  // pinned: data-attr values are wire strings
                  pinned: { order: 0, variant: 'primary', dataAttr: 'cross-project-add-tile' },
              },
              {
                  group: 'file',
                  section: 'delete',
                  id: `${RESOURCE_TYPE}-menubar-delete`,
                  label: 'Delete dashboard',
                  icon: <IconTrash />,
                  destructive: true,
                  onSelect: () => deleteDashboard(),
              },
              ...(!layoutEditMode && tiles.length > 0
                  ? ([
                        {
                            group: 'edit',
                            section: 'layout',
                            id: `${RESOURCE_TYPE}-menubar-customize`,
                            label: 'Customize',
                            icon: <IconGridMasonry />,
                            onSelect: () => enterLayoutEdit(),
                            pinned: layoutPin,
                        },
                    ] satisfies SceneAction[])
                  : []),
              ...(layoutEditMode
                  ? ([
                        {
                            group: 'edit',
                            section: 'layout',
                            id: `${RESOURCE_TYPE}-menubar-save-layout`,
                            label: 'Save layout',
                            icon: <IconCheck />,
                            disabledReason: dashboardLoading ? 'Wait for dashboard to finish loading' : undefined,
                            onSelect: () => saveLayout(),
                            pinned: layoutPin,
                        },
                        {
                            group: 'edit',
                            section: 'layout',
                            id: `${RESOURCE_TYPE}-menubar-cancel-layout`,
                            label: 'Cancel layout changes',
                            icon: <IconX />,
                            onSelect: () => cancelLayoutEdit(),
                        },
                    ] satisfies SceneAction[])
                  : []),
              {
                  group: 'view',
                  section: 'filters',
                  type: 'panel',
                  id: `${RESOURCE_TYPE}-menubar-date-range`,
                  label: 'Date range',
                  icon: <IconCalendar />,
                  render: () => (
                      <DateFilter
                          dateFrom={dashboardFilters.date_from ?? null}
                          dateTo={dashboardFilters.date_to ?? null}
                          onChange={setDates}
                      />
                  ),
                  pinned: {
                      order: 0,
                      variant: 'icon',
                      render: () => (
                          <DateFilter
                              dateFrom={dashboardFilters.date_from ?? null}
                              dateTo={dashboardFilters.date_to ?? null}
                              onChange={setDates}
                          />
                      ),
                  },
              },
              {
                  group: 'view',
                  section: 'filters',
                  type: 'radio',
                  id: `${RESOURCE_TYPE}-menubar-interval`,
                  label: 'Interval',
                  icon: <IconClock />,
                  value: dashboardFilters.interval ?? DEFAULT_INTERVAL,
                  options: INTERVAL_OPTIONS,
                  onValueChange: (value) => setInterval(value === DEFAULT_INTERVAL ? null : (value as IntervalType)),
                  pinned: { order: 1, variant: 'icon', dataAttr: 'cross-project-interval-filter' },
              },
          ]
        : []

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
