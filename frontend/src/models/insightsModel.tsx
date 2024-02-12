import { actions, connect, kea, listeners, path } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { promptLogic } from 'lib/logic/promptLogic'
import { teamLogic } from 'scenes/teamLogic'

import { InsightModel } from '~/types'

import type { insightsModelType } from './insightsModelType'

export const insightsModel = kea<insightsModelType>([
    path(['models', 'insightsModel']),
    connect([promptLogic({ key: 'rename-insight' }), teamLogic]),
    actions(() => ({
        renameInsight: (item: InsightModel) => ({ item }),
        renameInsightSuccess: (item: InsightModel) => ({ item }),
        //TODO this duplicates the insight but not the dashboard tile (e.g. if duplicated from dashboard you lose tile color
        duplicateInsight: (item: InsightModel, dashboardId?: number) => ({
            item,
            dashboardId,
        }),
        duplicateInsightSuccess: (item: InsightModel) => ({ item }),
        insightsAddedToDashboard: ({ dashboardId, insightIds }: { dashboardId: number; insightIds: number[] }) => ({
            dashboardId,
            insightIds,
        }),
    })),
    listeners(({ actions }) => ({
        renameInsight: async ({ item }) => {
            promptLogic({ key: 'rename-insight' }).actions.prompt({
                title: 'Rename insight',
                placeholder: 'Please enter the new name',
                value: item.name,
                error: 'You must enter name',
                success: async (name: string) => {
                    const updatedItem = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`,
                        {
                            name,
                        }
                    )
                    lemonToast.success(
                        <>
                            Renamed insight from <b>{item.name}</b> to <b>{name}</b>
                        </>
                    )
                    actions.renameInsightSuccess(updatedItem)
                },
            })
        },
        duplicateInsight: async ({ item }) => {
            if (!item) {
                return
            }

            const { id: _discard, short_id: __discard, ...rest } = item
            const newItem = { ...rest, name: (rest.name || rest.derived_name) + ' (copy)' }
            const addedItem = await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights`, newItem)

            actions.duplicateInsightSuccess(addedItem)
            lemonToast.success('Insight duplicated')
        },
    })),
])
