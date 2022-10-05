import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { prompt } from 'lib/logic/prompt'
import { InsightModel } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import type { insightsModelType } from './insightsModelType'
import { lemonToast } from 'lib/components/lemonToast'

export const insightsModel = kea<insightsModelType>({
    path: ['models', 'insightsModel'],
    connect: [prompt({ key: 'rename-insight' }), teamLogic],
    actions: () => ({
        renameInsight: (item: InsightModel) => ({ item }),
        renameInsightSuccess: (item: InsightModel) => ({ item }),
        duplicateInsight: (item: InsightModel, dashboardId?: number) => ({
            item,
            dashboardId,
        }),
        duplicateInsightSuccess: (item: InsightModel) => ({ item }),
    }),
    listeners: ({ actions }) => ({
        renameInsight: async ({ item }) => {
            prompt({ key: 'rename-insight' }).actions.prompt({
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
    }),
})
