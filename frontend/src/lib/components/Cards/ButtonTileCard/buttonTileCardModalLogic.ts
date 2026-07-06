import { connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, QueryBasedInsightModel } from '~/types'

import type { buttonTileCardModalLogicType } from './buttonTileCardModalLogicType'

export interface ButtonTileForm {
    url: string
    text: string
    placement: 'left' | 'right'
    style: 'primary' | 'secondary'
    transparent_background: boolean
}

export interface ButtonTileCardModalProps {
    dashboard: DashboardType<QueryBasedInsightModel>
    buttonTileId: number | 'new'
    onClose: () => void
}

const getExistingButtonTile = (
    dashboard: DashboardType<QueryBasedInsightModel>,
    buttonTileId: number
): ButtonTileForm => {
    const tile = dashboard.tiles?.find((t) => t.id === buttonTileId)
    if (tile?.button_tile) {
        return {
            url: tile.button_tile.url,
            text: tile.button_tile.text,
            placement: tile.button_tile.placement,
            style: tile.button_tile.style,
            transparent_background: tile.transparent_background ?? false,
        }
    }
    return { url: '', text: '', placement: 'left', style: 'primary', transparent_background: false }
}

const ALLOWED_URL_PROTOCOLS = ['http:', 'https:']

const isValidUrl = (value: string): boolean => {
    try {
        const url = new URL(value)
        return ALLOWED_URL_PROTOCOLS.includes(url.protocol)
    } catch {
        return false
    }
}

const isValidPathname = (value: string): boolean => {
    return /^\/[a-zA-Z0-9._~:/?#[\]@!$&'()*+,;=%-]*$/.test(value)
}

export const buttonTileCardModalLogic = kea<buttonTileCardModalLogicType>([
    path(['scenes', 'dashboard', 'buttonTileCardModal', 'logic']),
    props({} as ButtonTileCardModalProps),
    key((props) => `buttonTileCardModalLogic-${props.dashboard.id}-${props.buttonTileId}`),
    connect(() => ({ actions: [dashboardsModel, ['updateDashboard']] })),
    listeners(({ props, actions }) => ({
        submitButtonTileFailure: (error) => {
            if (props.dashboard && props.buttonTileId) {
                lemonToast.error(`Could not save button: ${error.error} (${JSON.stringify(error.errors)})`)
            }
            actions.resetButtonTile()
            props?.onClose?.()
        },
        submitButtonTileSuccess: ({ buttonTile }: { buttonTile: ButtonTileForm }) => {
            actions.resetButtonTile()
            props?.onClose?.()

            posthog.capture('dashboard button tile saved', {
                dashboard_id: props.dashboard.id,
                button_tile_id: props.buttonTileId === 'new' ? null : props.buttonTileId,
                is_new: props.buttonTileId === 'new',
                url_type: buttonTile.url.startsWith('/') ? 'pathname' : 'full_url',
            })
        },
    })),
    forms(({ props, actions }) => ({
        buttonTile: {
            defaults: (props.buttonTileId && props.buttonTileId !== 'new'
                ? getExistingButtonTile(props.dashboard, props.buttonTileId)
                : {
                      url: '',
                      text: '',
                      placement: 'left',
                      style: 'primary',
                      transparent_background: false,
                  }) as ButtonTileForm,
            errors: ({ url, text }) => ({
                url: !url
                    ? 'URL is required'
                    : url.startsWith('/')
                      ? !isValidPathname(url)
                          ? 'Must be a valid pathname starting with /'
                          : null
                      : !isValidUrl(url)
                        ? 'Must be a valid URL (e.g. https://example.com) or a pathname starting with /'
                        : null,
                text: !text ? 'Button text is required' : null,
            }),
            submit: (formValues) => {
                const { transparent_background, ...buttonTileFields } = formValues
                const tiles = (props.dashboard.tiles || []).map((t) => ({
                    id: t.id,
                    button_tile: t.button_tile,
                    transparent_background: t.transparent_background,
                }))

                if (props.buttonTileId === 'new') {
                    actions.updateDashboard({
                        id: props.dashboard.id,
                        tiles: [{ button_tile: buttonTileFields, transparent_background }],
                    })
                } else {
                    const updatedTiles = tiles.map((tile) => {
                        if (tile.id === props.buttonTileId && tile.button_tile) {
                            return {
                                ...tile,
                                button_tile: { ...tile.button_tile, ...buttonTileFields },
                                transparent_background,
                            }
                        }
                        return tile
                    })
                    actions.updateDashboard({ id: props.dashboard.id, tiles: updatedTiles })
                }
            },
        },
    })),
])
