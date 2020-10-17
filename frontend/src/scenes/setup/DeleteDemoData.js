import React from 'react'
import { kea, useActions, useValues } from 'kea'
import api from '../../lib/api'
import { Button } from 'antd'
import { dashboardsModel } from '~/models'

const deleteDemoDataLogic = kea({
    actions: () => ({
        deleteDemoData: true,
        demoDataDeleted: true,
    }),
    reducers: ({ actions }) => ({
        isDeleted: [
            false,
            {
                [actions.demoDataDeleted]: () => true,
            },
        ],
    }),
    listeners: ({ actions }) => ({
        [actions.deleteDemoData]: async () => {
            await api.get('delete_demo_data')
            actions.demoDataDeleted()
            dashboardsModel.actions.loadDashboards()
        },
    }),
})

export function DeleteDemoData() {
    const { isDeleted } = useValues(deleteDemoDataLogic)
    const { deleteDemoData } = useActions(deleteDemoDataLogic)
    return (
        <div>
            <Button type="primary" danger onClick={deleteDemoData}>
                Delete demo data
            </Button>
            {isDeleted && <p className="text-success">Demo data deleted!</p>}
        </div>
    )
}
