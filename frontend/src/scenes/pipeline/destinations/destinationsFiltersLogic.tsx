import { LemonDialog, LemonInput, LemonTextArea, lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionTypeType } from '~/types'

import { PipelineBackend } from '../types'
import type { destinationsFiltersLogicType } from './destinationsFiltersLogicType'

export type DestinationsFilters = {
    search?: string
    kind?: PipelineBackend | null
    showPaused?: boolean
}

export interface DestinationsFiltersLogicProps {
    types: HogFunctionTypeType[]
}

export const destinationsFiltersLogic = kea<destinationsFiltersLogicType>([
    path(() => ['scenes', 'pipeline', 'destinations', 'destinationsFiltersLogic']),
    props({} as DestinationsFiltersLogicProps),
    key((props) => props.types.join(',') ?? ''),
    connect(() => ({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setFilters: (filters: Partial<DestinationsFilters>) => ({ filters }),
        resetFilters: true,
        openFeedbackDialog: true,
    }),
    reducers(({ props }) => ({
        filters: [
            {} as DestinationsFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({
                    showPaused: true,
                }),
            },
        ],
        types: [props.types, {}],
    })),

    listeners(({ values }) => ({
        setFilters: async ({ filters }, breakpoint) => {
            if (filters.search && filters.search.length > 2) {
                await breakpoint(1000)
                posthog.capture('cdp destination search', { search: filters.search })
            }
        },

        openFeedbackDialog: async (_, breakpoint) => {
            const isTransformation = values.types.includes('transformation')
            const itemType = isTransformation ? 'transformation' : 'destination'

            await breakpoint(100)
            LemonDialog.openForm({
                title: `What ${itemType} would you like to see?`,
                initialValues: { destination_name: values.filters.search },
                errors: {
                    destination_name: (x) => (!x ? 'Required' : undefined),
                },
                description: undefined,
                content: (
                    <div className="deprecated-space-y-2">
                        <LemonField name="destination_name" label={isTransformation ? 'Transformation' : 'Destination'}>
                            <LemonInput placeholder={`What ${itemType} would you like to see?`} autoFocus />
                        </LemonField>
                        <LemonField name="destination_details" label="Additional information" showOptional>
                            <LemonTextArea
                                placeholder={`Any extra details about what you would need this ${itemType} to do or your overall goal`}
                            />
                        </LemonField>
                    </div>
                ),
                onSubmit: async (values) => {
                    posthog.capture(`cdp ${itemType} feedback`, { ...values })
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
        ['/pipeline/*']: (_, searchParams) => {
            if (!objectsEqual(values.filters, searchParams)) {
                actions.setFilters(searchParams)
            }
        },
    })),
])
