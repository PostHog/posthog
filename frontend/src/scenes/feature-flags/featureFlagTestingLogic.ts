import { actions, connect, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api'
import { dayjs, Dayjs } from 'lib/dayjs'
import { projectLogic } from 'scenes/projectLogic'

import { PersonType } from '~/types'

import { featureFlagsTestEvaluationCreate } from 'products/feature_flags/frontend/generated/api'
import type {
    FeatureFlagConditionAnalysisApi,
    FeatureFlagConditionPropertyAnalysisApi,
    FeatureFlagTestEvaluationRequestApi,
    FeatureFlagTestEvaluationResponseApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

import type { featureFlagTestingLogicType } from './featureFlagTestingLogicType'

export type PropertyAnalysis = FeatureFlagConditionPropertyAnalysisApi
export type ConditionAnalysis = FeatureFlagConditionAnalysisApi
export type TestResult = FeatureFlagTestEvaluationResponseApi

export interface TestFormData {
    distinct_id: string
    person_id: string
    timestamp: string
    groups: string
}

const EMPTY_FORM: TestFormData = { distinct_id: '', person_id: '', timestamp: '', groups: '' }

export interface FeatureFlagTestingLogicProps {
    flagId: number
}

export const featureFlagTestingLogic = kea<featureFlagTestingLogicType>([
    props({} as FeatureFlagTestingLogicProps),
    key((props) => props.flagId),
    path((key) => ['scenes', 'feature-flags', 'featureFlagTestingLogic', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        setTestFormData: (formData: Partial<TestFormData>) => ({ formData }),
        setTestError: (error: string | null) => ({ error }),
        setShowAllProperties: (showAll: boolean) => ({ showAll }),
        setDatePickerOpen: (open: boolean) => ({ open }),
        setDatePickerValue: (value: Dayjs | null) => ({ value }),
        setSelectedPerson: (person: PersonType | null) => ({ person }),
        clearTestForm: true,
    }),
    loaders(({ values }) => ({
        testEvaluation: [
            null as TestResult | null,
            {
                testFlagEvaluation: async ({ flagId, formData }: { flagId: number; formData: TestFormData }) => {
                    const data: FeatureFlagTestEvaluationRequestApi = {}

                    if (formData.person_id?.trim()) {
                        data.person_id = formData.person_id.trim()
                    } else if (formData.distinct_id?.trim()) {
                        data.distinct_id = formData.distinct_id.trim()
                    }

                    if (formData.groups?.trim()) {
                        try {
                            const parsed = JSON.parse(formData.groups.trim())
                            if (typeof parsed !== 'object' || Array.isArray(parsed)) {
                                throw new Error('groups must be a JSON object')
                            }
                            data.groups = formData.groups.trim()
                        } catch (e) {
                            if (e instanceof SyntaxError) {
                                throw new Error('Invalid JSON format for groups')
                            }
                            throw e
                        }
                    } else {
                        data.groups = '{}'
                    }

                    if (formData.timestamp?.trim()) {
                        data.timestamp = formData.timestamp.trim()

                        const parsedTimestamp = dayjs(data.timestamp)
                        if (!parsedTimestamp.isValid()) {
                            throw new Error('Invalid timestamp format')
                        }
                    }

                    return await featureFlagsTestEvaluationCreate(String(values.currentProjectId), flagId, data)
                },
            },
        ],
    })),
    reducers({
        testFormData: [
            EMPTY_FORM,
            {
                setTestFormData: (state, { formData }) => ({ ...state, ...formData }),
                clearTestForm: () => EMPTY_FORM,
            },
        ],
        testError: [
            null as string | null,
            {
                setTestError: (_, { error }: { error: string | null }) => error,
                testFlagEvaluation: () => null,
                testFlagEvaluationFailure: (_, { error, errorObject }: { error: string; errorObject?: unknown }) => {
                    const apiError = errorObject as ApiError
                    if (apiError?.detail) {
                        const errorDetail = apiError.detail

                        if (errorDetail.includes('Failed to build person properties at specified timestamp')) {
                            return 'Unable to build person properties at the selected timestamp. This person may not have had any recorded activity at that time, or the timestamp may be too far in the past.'
                        }

                        if (errorDetail.includes('person') && errorDetail.includes('not found')) {
                            return 'Person not found. This person may not have existed at the selected timestamp.'
                        }

                        if (errorDetail.includes('timestamp') || errorDetail.includes('time')) {
                            return 'Invalid timestamp. Please select a valid date and time.'
                        }

                        return errorDetail
                    }

                    const errorMessage = apiError?.message || error || ''
                    if (errorMessage.includes('Failed to build person properties at specified timestamp')) {
                        return 'Unable to build person properties at the selected timestamp. This person may not have had any recorded activity at that time, or the timestamp may be too far in the past.'
                    }

                    return errorMessage || 'An unexpected error occurred while testing the feature flag'
                },
            },
        ],
        testResult: [
            null as TestResult | null,
            {
                testFlagEvaluationSuccess: (_, { testEvaluation }) => testEvaluation,
                clearTestForm: () => null,
            },
        ],
        showAllProperties: [
            false,
            {
                setShowAllProperties: (_, { showAll }) => showAll,
                clearTestForm: () => false,
            },
        ],
        datePickerOpen: [
            false,
            {
                setDatePickerOpen: (_, { open }) => open,
            },
        ],
        datePickerValue: [
            null as Dayjs | null,
            {
                setDatePickerValue: (_, { value }) => (value === undefined ? null : value),
                clearTestForm: () => null,
            },
        ],
        selectedPerson: [
            null as PersonType | null,
            {
                setSelectedPerson: (_, { person }) => person,
                clearTestForm: () => null,
            },
        ],
    }),
])
