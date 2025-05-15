import { actions, events, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import type { hedgedHogBetDefinitionsLogicType } from './hedgedHogBetDefinitionsLogicType'

export interface BetParameters {
    url?: string
    [key: string]: any
}

export interface BetDefinition {
    id: string
    team: string
    type: string
    bet_parameters: BetParameters
    closing_date: string
    status: string
    probability_distribution_interval: number
    title: string
    description: string
    created_at: string
    latest_distribution?: {
        id: string
        created_at: string
        buckets: Array<{
            min: number
            max: number
            probability: number
        }>
    }
    probability_distributions: Array<{
        id: string
        created_at: string
        buckets: Array<{
            min: number
            max: number
            probability: number
        }>
    }>
    final_value?: any
}

export interface BetDefinitionPayload {
    title: string
    description: string
    type: string
    bet_parameters: BetParameters
    closing_date: string
    probability_distribution_interval: number
}

export interface BetEstimatePayload {
    bet_definition: string
    amount: number
    predicted_value: number
}

export interface BetEstimateResponse {
    amount: number
    predicted_value: number
    payout_multiplier: number
    potential_payout: number
}

const DEFAULT_BET_DEFINITION: BetDefinitionPayload = {
    title: '',
    description: '',
    type: 'pageviews',
    bet_parameters: { url: '' },
    closing_date: dayjs().add(7, 'day').toISOString(),
    probability_distribution_interval: 600,
}

export const hedgedHogBetDefinitionsLogic = kea<hedgedHogBetDefinitionsLogicType>([
    path(['scenes', 'hedged-hog', 'hedgedHogBetDefinitionsLogic']),

    actions({
        setShowNewForm: (show: boolean) => ({ show }),
        estimateBetPayout: (amount: number, predictedValue: number) => ({ amount, predictedValue }),
        resetBetEstimate: () => ({}),
        addBetDefinitionToList: (betDefinition: BetDefinition) => ({ betDefinition }),
    }),

    reducers({
        showNewForm: [
            false,
            {
                setShowNewForm: (_, { show }) => show,
                submitBetDefinitionSuccess: () => false,
            },
        ],
        currentBetDefinitionId: [
            null as string | null,
            {
                setCurrentBetDefinitionId: (_, { id }) => id,
            },
        ],
        betEstimate: [
            null as BetEstimateResponse | null,
            {
                estimateBetPayoutSuccess: (_, { betEstimate }) => betEstimate,
                resetBetEstimate: () => null,
            },
        ],
        betDefinitions: [
            [] as BetDefinition[],
            {
                loadBetDefinitionsSuccess: (_, { betDefinitions }) => betDefinitions,
                addBetDefinitionToList: (state, { betDefinition }) => [betDefinition, ...state],
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        betDefinitions: [
            [] as BetDefinition[],
            {
                loadBetDefinitions: async () => {
                    const response = await api.get('api/projects/@current/bet_definitions/')
                    return response.results
                },
            },
        ],
        betDefinition: [
            DEFAULT_BET_DEFINITION,
            {
                loadBetDefinition: async (id: string) => {
                    const response = await api.get(`api/projects/@current/bet_definitions/${id}/`)
                    return {
                        title: response.title,
                        description: response.description,
                        type: response.type,
                        bet_parameters: response.bet_parameters,
                        closing_date: response.closing_date,
                        probability_distribution_interval: response.probability_distribution_interval,
                    }
                },
                settleBetDefinition: async ({ id, finalValue }: { id: string; finalValue: number }) => {
                    const response = await api.create(`api/projects/@current/bet_definitions/${id}/settle/`, {
                        final_value: finalValue,
                    })
                    actions.loadBetDefinitions()
                    return response
                },
            },
        ],
        betEstimate: [
            null as BetEstimateResponse | null,
            {
                estimateBetPayout: async ({ amount, predictedValue }) => {
                    if (!values.currentBetDefinitionId) {
                        return null
                    }
                    const payload: BetEstimatePayload = {
                        bet_definition: values.currentBetDefinitionId,
                        amount,
                        predicted_value: predictedValue,
                    }
                    const response = await api.create('api/projects/@current/bets/estimate/', payload)
                    return response
                },
            },
        ],
    })),
    forms(({ actions }) => ({
        betDefinition: {
            defaults: DEFAULT_BET_DEFINITION,
            submit: async (values) => {
                const response = await api.create('api/projects/@current/bet_definitions/', values)
                actions.addBetDefinitionToList(response)
                actions.loadBetDefinitions()
                return response
            },
        },
    })),

    selectors({
        activeBetDefinitions: [
            (s) => [s.betDefinitions],
            (betDefinitions) => betDefinitions.filter((b) => b.status === 'active'),
        ],
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadBetDefinitions()
        },
    })),
])
