import { LemonDialog, LemonInput, LemonTextArea, lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import { PipelineBackend } from '../types'

export type DestinationsFilters = {
    search?: string
    kind?: PipelineBackend | null
    sub_template?: string
    showPaused?: boolean
}

export const destinationsFiltersLogic = kea([
    path(() => ['scenes', 'pipeline', 'destinations', 'destinationsFiltersLogic']),
    connect({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setFilters: (filters: Partial<DestinationsFilters>) => ({ filters }),
        resetFilters: true,
        openFeedbackDialog: true,
    }),
    reducers(({}) => ({
        filters: [
            {} as DestinationsFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({}),
            },
        ],
    })),

    listeners(({ values }) => ({
        setFilters: async ({ filters }, breakpoint) => {
            if (filters.search && filters.search.length > 2) {
                await breakpoint(1000)
                posthog.capture('cdp destination search', { search: filters.search })
            }
            console.log('filters', filters)
        },

        openFeedbackDialog: async (_, breakpoint) => {
            await breakpoint(100)
            LemonDialog.openForm({
                title: 'What destination would you like to see?',
                initialValues: { destination_name: values.filters.search },
                errors: {
                    destination_name: (x) => (!x ? 'Required' : undefined),
                },
                description: undefined,
                content: (
                    <div className="space-y-2">
                        <LemonField name="destination_name" label="Destination">
                            <LemonInput placeholder="What destination would you like to see?" autoFocus />
                        </LemonField>
                        <LemonField name="destination_details" label="Additional information" showOptional>
                            <LemonTextArea placeholder="Any extra details about what you would need this destination to do or your overall goal" />
                        </LemonField>
                    </div>
                ),
                onSubmit: async (values) => {
                    posthog.capture('cdp destination feedback', { ...values })
                    lemonToast.success('Thank you for your feedback!')
                },
            })
        },
    })),

    actionToUrl(({ values }) => {
        const urlFromFilters = (): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => [
            router.values.location.pathname,
            {
                ...values.filters,
            },
            router.values.hashParams,
            {
                replace: true,
            },
        ]

        return {
            setFilters: () => urlFromFilters(),
            resetFilters: () => urlFromFilters(),
        }
    }),

    urlToAction(({ actions, values }) => ({
        ['*']: (_, searchParams) => {
            if (!objectsEqual(values.filters, searchParams)) {
                actions.setFilters(searchParams)
            }
        },
    })),
])
