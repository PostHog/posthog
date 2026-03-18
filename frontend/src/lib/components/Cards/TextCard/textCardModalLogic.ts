import { connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import type { textCardModalLogicType } from './textCardModalLogicType'

export interface TextTileForm {
    body: string
}

export interface TextCardModalProps {
    dashboard: DashboardType<QueryBasedInsightModel>
    textTileId: number | 'new'
    onClose: () => void
}

const MAX_TEXT_CARD_BODY_LENGTH = 4000

const getTileBody = (dashboard: DashboardType<QueryBasedInsightModel>, textTileId: number): string => {
    const dashboardTiles = dashboard.tiles
    const matchedTile = dashboardTiles?.find((tt) => tt.id === textTileId)
    return matchedTile?.text?.body || ''
}

export const textCardModalLogic = kea<textCardModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardTextTileModal', 'logic']),
    props({} as TextCardModalProps),
    key((props) => `textCardModalLogic-${props.dashboard.id}-${props.textTileId}`),
    connect(() => ({ actions: [dashboardsModel, ['updateDashboard']] })),
    listeners(({ props, actions, values }) => ({
        submitTextTileFailure: (error) => {
            if (props.dashboard && props.textTileId) {
                const failure = error as {
                    errors?: Record<string, any>
                    error?: string | { error?: string; errors?: Record<string, any> }
                }
                const normalizedErrors = (failure.errors ||
                    (typeof failure.error === 'object' ? failure.error?.errors : undefined) ||
                    {}) as Record<string, any>
                const normalizedMessage =
                    (typeof failure.error === 'string' ? failure.error : null) ||
                    (typeof failure.error === 'object' && typeof failure.error?.error === 'string'
                        ? failure.error.error
                        : null) ||
                    'Unknown error'
                const formBodyError = values.textTileValidationErrors.body as string | null
                const apiBodyError =
                    (Array.isArray(normalizedErrors?.body) ? normalizedErrors.body[0] : normalizedErrors?.body) ||
                    (Array.isArray(normalizedErrors?.text?.body)
                        ? normalizedErrors.text.body[0]
                        : normalizedErrors?.text?.body) ||
                    null

                // Expected validation errors are shown inline on the form.
                if (formBodyError || apiBodyError) {
                    return
                }

                lemonToast.error(`Could not save text: ${normalizedMessage}`)
            }
        },
        submitTextTileSuccess: ({ textTile }: { textTile: TextTileForm }) => {
            actions.resetTextTile()
            props?.onClose?.()

            posthog.capture('dashboard text tile saved', {
                dashboard_id: props.dashboard.id,
                text_tile_id: props.textTileId === 'new' ? null : props.textTileId,
                is_new: props.textTileId === 'new',
                body_length: textTile.body.length,
            })
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
                    body: !body.trim()
                        ? 'This card would be empty! Type something first'
                        : body.length > MAX_TEXT_CARD_BODY_LENGTH
                          ? `Text is too long (${MAX_TEXT_CARD_BODY_LENGTH} characters max)`
                          : null,
                }
            },
            submit: (formValues) => {
                // only id and body, layout and color could be out-of-date
                const textTiles = (props.dashboard.tiles || []).map((t) => ({ id: t.id, text: t.text }))

                if (props.textTileId === 'new') {
                    actions.updateDashboard({ id: props.dashboard.id, tiles: [{ text: formValues }] })
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
