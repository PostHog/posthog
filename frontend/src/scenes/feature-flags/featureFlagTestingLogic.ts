import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api'
import { dayjs, Dayjs } from 'lib/dayjs'
import { projectLogic } from 'scenes/projectLogic'

import { PersonType } from '~/types'

import { featureFlagsTestEvaluationCreate } from 'products/feature_flags/frontend/generated/api'
import type {
    FeatureFlagConditionAnalysisApi,
    FeatureFlagTestEvaluationRequestApi,
    FeatureFlagTestEvaluationResponseApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

import type { featureFlagTestingLogicType } from './featureFlagTestingLogicType'

export type ConditionAnalysis = FeatureFlagConditionAnalysisApi
export type TestResult = FeatureFlagTestEvaluationResponseApi

export interface TestFormData {
    person_id: string
    timestamp: string
    groups: string
}

const EMPTY_FORM: TestFormData = { person_id: '', timestamp: '', groups: '' }

function validateAndParseGroups(groups: string): Record<string, any> {
    const trimmed = groups.trim()
    if (!trimmed) {
        return {}
    }

    try {
        const parsed = JSON.parse(trimmed)
        if (typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('groups must be a JSON object')
        }
        return parsed
    } catch (e) {
        throw e instanceof SyntaxError ? new Error('Invalid JSON format for groups') : e
    }
}

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
        setDatePickerOpen: (open: boolean) => ({ open }),
        setDatePickerValue: (value: Dayjs | null) => ({ value }),
        setSelectedPerson: (person: PersonType | null) => ({ person }),
        setIncludeTime: (includeTime: boolean) => ({ includeTime }),
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
                    }

                    data.groups = validateAndParseGroups(formData.groups || '')

                    if (formData.timestamp?.trim()) {
                        data.timestamp = formData.timestamp.trim()

                        // Validate ISO string format with strict parsing
                        const parsedTimestamp = dayjs(data.timestamp, 'YYYY-MM-DDTHH:mm:ss.SSS[Z]', true)
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
                clearTestForm: () => null,
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

                        if (errorDetail.includes('timestamp') || errorDetail.toLowerCase() === 'invalid timestamp') {
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
                setTestFormData: () => null,
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
                setDatePickerValue: (_, { value }) => value,
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
        includeTime: [
            true,
            {
                setIncludeTime: (_, { includeTime }) => includeTime,
            },
        ],
    }),
    selectors({
        // Get the set of properties used in any condition
        usedProperties: [
            (s) => [s.testResult],
            (result: TestResult | null): Set<string> => {
                const used = new Set<string>()
                if (result?.conditions) {
                    for (const condition of result.conditions) {
                        for (const prop of condition.properties) {
                            used.add(prop.key)
                        }
                    }
                }
                return used
            },
        ],
        // Get enriched conditions with derived flags for UI rendering
        enrichedConditions: [
            (s) => [s.testResult],
            (result: TestResult | null) => {
                if (!result?.conditions) {
                    return []
                }

                return result.conditions.map((condition: ConditionAnalysis) => {
                    // Check if this condition is the actual winner
                    // Per the API serializer, matched is the source of truth - "at most one condition per flag is True"
                    const isWinningCondition = condition.matched
                    // Determine if this condition matched but wasn't the winner
                    const matchedButNotWinner =
                        condition.properties_matched && !isWinningCondition && !condition.rollout_excluded

                    // Determine display properties
                    let tone: 'success' | 'info' | 'warning' | 'muted' = 'muted'
                    let label: string | null = null

                    if (isWinningCondition) {
                        tone = 'success'
                        label = 'MATCHED'
                    } else if (matchedButNotWinner) {
                        tone = 'info'
                        label = 'PROPERTIES MATCHED'
                    } else if (condition.rollout_excluded) {
                        tone = 'warning'
                        label = 'EXCLUDED FROM ROLLOUT'
                    }

                    return {
                        ...condition,
                        isWinningCondition,
                        matchedButNotWinner,
                        display: {
                            tone,
                            label,
                        },
                    }
                })
            },
        ],
        // Check if form has valid person selected
        hasValidPerson: [
            (s) => [s.testFormData],
            (formData: TestFormData): boolean => Boolean(formData.person_id?.trim()),
        ],
        // Get formatted error display information
        errorDisplay: [
            (s) => [s.testError],
            (error: string | null) => {
                if (!error) {
                    return null
                }

                let helpText: string | null = null

                if (error.toLowerCase().includes('build person properties')) {
                    helpText =
                        'Try a more recent timestamp when this person was active, remove the timestamp to test with current person properties, or select a different person who was active at that time.'
                } else if (error.toLowerCase().includes('person') && error.toLowerCase().includes('not found')) {
                    helpText = 'Try selecting a different person or removing the timestamp to test with current data.'
                } else if (error.toLowerCase().includes('timestamp')) {
                    helpText =
                        'When using historical timestamps, the person must have existed at that time and had the necessary properties for evaluation.'
                }

                return {
                    message: error,
                    helpText,
                }
            },
        ],
    }),
])
