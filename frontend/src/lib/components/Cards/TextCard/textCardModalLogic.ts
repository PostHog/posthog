import { lemonToast } from '@posthog/lemon-ui'
import { kea, props, path, connect, key, listeners } from 'kea'
import { forms } from 'kea-forms'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardTile, DashboardType } from '~/types'

import type { textCardModalLogicType } from './textCardModalLogicType'
import api from 'lib/api'
import { toast } from 'react-toastify'

export interface TextTileForm {
    body: string
}

export interface TextCardModalProps {
    dashboard: DashboardType
    textTileId: number | 'new'
    onClose: () => void
}

const getTileBody = (dashboard: DashboardType, textTileId: number): string => {
    const dashboardTiles = dashboard.tiles
    const matchedTile = dashboardTiles?.find((tt) => tt.id === textTileId)
    return matchedTile?.text?.body || ''
}

export const textCardModalLogic = kea<textCardModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardTextTileModal', 'logic']),
    props({} as TextCardModalProps),
    key((props) => `textCardModalLogic-${props.dashboard.id}-${props.textTileId}`),
    connect({ actions: [dashboardsModel, ['tileAddedToDashboard']] }),
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
            submit: async (formValues) => {
                // only id and body, layout and color could be out-of-date
                const textTiles = (props.dashboard.tiles || []).map((t) => ({ id: t.id, text: t.text }))

                if (props.textTileId === 'new') {
                    try {
                        await api.dashboardTiles.addText(formValues, props.dashboard.id)
                        actions.tileAddedToDashboard(props.dashboard.id)
                    } catch (e: any) {
                        toast.error('Could not add text to dashboard: ', e)
                    }
                } else {
                    const updatedTiles = [...textTiles].reduce((acc, tile) => {
                        if (tile.id === props.textTileId && tile.text) {
                            tile.text.body = formValues.body
                            acc.push(tile)
                        }
                        return acc
                    }, [] as Partial<DashboardTile>[])
                    actions.updateDashboard({ id: props.dashboard.id, tiles: updatedTiles })
                }
            },
        },
    })),
])
