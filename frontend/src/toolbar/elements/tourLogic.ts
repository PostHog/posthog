import { kea } from 'kea'
import { ElementsEventType } from '~/toolbar/types'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { posthog } from '~/toolbar/posthog'
import { tourLogicType } from './tourLogicType'

export const tourLogic = kea<tourLogicType>({
    actions: {
        enableTour: true,
        disableTour: true,
        setShowTourTooltip: (showTourTooltip: boolean) => ({ showTourTooltip }),
        setTourFilter: (filter: Record<string, any>) => ({ filter }),
    },

    reducers: {
        tourEnabled: [
            false,
            {
                enableTour: () => true,
                disableTour: () => false,
                getToursFailure: () => false,
            },
        ],
        tourLoading: [
            false,
            {
                getTours: () => true,
                getToursSuccess: () => false,
                getToursFailure: () => false,
                resetTours: () => false,
            },
        ],
        showTourTooltip: [
            false,
            {
                setShowTourTooltip: (_, { showTourTooltip }) => showTourTooltip,
            },
        ],
        tourFilter: [
            {} as Record<string, any>,
            {
                setTourFilter: (_, { filter }) => filter,
            },
        ],
    },

    loaders: ({ values }) => ({
        tours: [
            [] as ElementsEventType[],
            {
                resetTours: () => [],
                getTours: async (_, breakpoint) => {
                    const params: Record<string, any> = {
                        temporary_token: toolbarLogic.values.temporaryToken,
                        ...values.tourFilter,
                    }

                    const url = `${toolbarLogic.values.apiURL}api/tours/${encodeParams(params, '?')}`
                    const response = await fetch(url)
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    if (!Array.isArray(results)) {
                        throw new Error('Error loading Tours data!')
                    }

                    return results
                },
            },
        ],
    }),

    selectors: {},

    events: ({ actions, values }) => ({
        afterMount() {
            if (values.tourEnabled) {
                actions.getTours({})
            }
        },
    }),

    listeners: ({ actions, values }) => ({
        [currentPageLogic.actionTypes.setHref]: () => {
            if (values.tourEnabled) {
                actions.resetTours()
                actions.getTours({})
            }
        },
        enableTour: () => {
            actions.getTours({})
            posthog.capture('toolbar mode triggered', { mode: 'tour', enabled: true })
        },
        disableTour: () => {
            actions.resetTours()
            actions.setShowTourTooltip(false)
            posthog.capture('toolbar mode triggered', { mode: 'tour', enabled: false })
        },
        getEventsSuccess: () => {
            actions.setShowTourTooltip(true)
        },
        setShowTourTooltip: async ({ showTourTooltip }, breakpoint) => {
            if (showTourTooltip) {
                await breakpoint(1000)
                actions.setShowTourTooltip(false)
            }
        },
        setTourFilter: () => {
            actions.getTours({})
        },
    }),
})
