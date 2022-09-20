import { lemonToast } from '@posthog/lemon-ui'
import { kea, props, path, connect, key, listeners } from 'kea'
import { forms } from 'kea-forms'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType } from '~/types'

import type { dashboardTextTileModalLogicType } from './dashboardTextTileModalLogicType'

export interface TextTileForm {
    body: string
}

export interface DashboardTextTileModalProps {
    dashboard: DashboardType
    textTileId: number | 'new'
    onClose: () => void
}

const getTileBody = (dashboard: DashboardType, textTileId: number): string => {
    const foundBody = dashboard.text_tiles.find((tt) => tt.id === textTileId)?.body
    if (foundBody === undefined) {
        throw new Error('could not find body for tile with id: ' + textTileId)
    }
    return foundBody
}

export const dashboardTextTileModalLogic = kea<dashboardTextTileModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardTextTileModal', 'logic']),
    props({} as DashboardTextTileModalProps),
    key((props) => `dashboardTextTileModalLogic-${props.dashboard.id}-${props.textTileId}`),
    connect({ actions: [dashboardsModel, ['updateDashboard']] }),
    listeners(({ props, actions }) => ({
        submitTextTileFailure: (error) => {
            if (props.dashboard && props.textTileId) {
                lemonToast.error(`Could not save text: ${error.error} (${JSON.stringify(error.errors)})`)
            }
            actions.resetTextTile()
            props?.onClose?.()
        },
        submitTextTileSuccess: () => {
            actions.resetTextTile()
            props?.onClose?.()
        },
    })),
    forms(({ props, actions }) => ({
        textTile: {
            defaults: {
                body:
                    props.textTileId && props.textTileId !== 'new'
                        ? getTileBody(props.dashboard, props.textTileId)
                        : '',
            } as TextTileForm,
            errors: ({ body }) => {
                return {
                    body: !body ? 'A text tile must have text content.' : null,
                }
            },
            submit: (formValues) => {
                // only id and body, layout and color could be out-of-date
                const textTiles = props.dashboard.text_tiles.map((t) => ({ id: t.id, body: t.body }))
                if (props.textTileId === 'new') {
                    actions.updateDashboard({ id: props.dashboard.id, text_tiles: [...textTiles, formValues] })
                } else {
                    const updatedTiles = [...textTiles].map((tile) => {
                        if (tile.id === props.textTileId) {
                            tile.body = formValues.body
                        }
                        return tile
                    })
                    actions.updateDashboard({ id: props.dashboard.id, text_tiles: updatedTiles })
                }
            },
        },
    })),
])
