import { kea, actions, reducers, props, path, connect, key } from 'kea'
import { forms } from 'kea-forms'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType } from '~/types'

import type { dashboardTextTileModalLogicType } from './dashboardTextTileModalLogicType'

export interface AddTextTileForm {
    body: string
}

export interface DashboardTextTileModalProps {
    dashboard?: DashboardType
}

export const dashboardTextTileModalLogic = kea<dashboardTextTileModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardTextTileModal', 'logic']),
    props({} as DashboardTextTileModalProps),
    key((props) => `dashboardTextTileModalLogic-${props.dashboard?.id}`),
    connect({ actions: [dashboardsModel, ['updateDashboard']] }),
    actions({ addNewTextTile: true, closeModal: true }),
    reducers({
        showAddTextTileModal: [false as boolean, { addNewTextTile: () => true, closeModal: () => false }],
    }),
    forms(({ props, actions }) => ({
        addTextTile: {
            defaults: {
                body: '',
            } as AddTextTileForm,
            errors: ({ body }) => ({
                body: !body ? 'A text tile must have text content.' : null,
            }),
            submit: (formValues) => {
                debugger
                if (props.dashboard) {
                    const textTiles = props.dashboard.text_tiles
                    actions.updateDashboard({ id: props.dashboard.id, text_tiles: [...textTiles, formValues] })
                }
                actions.closeModal()
            },
        },
    })),
])
