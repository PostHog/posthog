import { kea } from 'kea'
import { TourType } from '~/toolbar/types'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { posthog } from '~/toolbar/posthog'
import { toursLogicType } from './toursLogicType'

export const toursLogic = kea<toursLogicType>({
    actions: {
        enableTour: true,
        disableTour: true,
        setShowToursTooltip: (showTourTooltip: boolean) => ({ showTourTooltip }),
        setTourFilter: (filter: Record<string, any>) => ({ filter }),
        setSlide: (slide: number) => ({ slide }),
        setTourName: (name: string) => ({ name }),
        setTourCohort: (cohort: number) => ({ cohort }),
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
        showToursTooltip: [
            false,
            {
                setShowToursTooltip: (_, { showTourTooltip }) => showTourTooltip,
            },
        ],
        tourFilter: [
            {} as Record<string, any>,
            {
                setTourFilter: (_, { filter }) => filter,
            },
        ],
        slide: [
            0,
            {
                setSlide: (_, { slide }) => slide,
            },
        ],
        tourName: [
            '',
            {
                setTourName: (_, { name }) => name,
            },
        ],
        tourCohort: [
            null as number | null,
            {
                setTourCohort: (_, { cohort }) => cohort,
            },
        ],
    },

    loaders: ({ values }) => ({
        tours: [
            [] as TourType[],
            {
                resetTours: () => [],
                getTours: async (_, breakpoint) => {
                    const params: Record<string, any> = {
                        temporary_token: toolbarLogic.values.temporaryToken,
                        ...values.tourFilter,
                    }

                    const url = `${toolbarLogic.values.apiURL}api/tours/${encodeParams(params, '?')}`
                    console.log('Fetching url', url)
                    // const response = await fetch(url)
                    // const results = await response.json()
                    const response = {
                        status: 200,
                    }
                    const results = [
                        {
                            uuid: '1',
                            created_at: '',
                            name: 'Test Product Tour',
                            cohort: 1,
                            start_url: 'https://www.posthog.com/*',
                            team_id: 1,
                            delay_ms: 200,
                            is_active: true,
                            steps: [
                                {
                                    html_el: 'div.navigation-inner > div.nth-child(3) > a',
                                    tooltip_title: 'Add a funnel step',
                                    tooltip_text: 'Click add funnel step to create a funnel.',
                                },
                                {
                                    html_el: 'div.navigation-inner > div.nth-child(3) > a',
                                    tooltip_title: 'Add breakdown',
                                    tooltip_text:
                                        'Use breakdown to see the aggregation for each value of that property.',
                                },
                            ],
                        },
                    ]

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

    selectors: {
        toursCount: [(selectors) => [selectors.tours], (tours: TourType[]) => tours.length],
    },

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
            actions.setShowToursTooltip(false)
            posthog.capture('toolbar mode triggered', { mode: 'tour', enabled: false })
        },
        getEventsSuccess: () => {
            actions.setShowToursTooltip(true)
        },
        setShowToursTooltip: async ({ showTourTooltip }, breakpoint) => {
            if (showTourTooltip) {
                await breakpoint(1000)
                actions.setShowToursTooltip(false)
            }
        },
        setTourFilter: () => {
            actions.getTours({})
        },
    }),
})
