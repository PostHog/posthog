import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
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
    distinct_id: string
    timestamp: string
    groups: string
}

// One row of a batch evaluation — how the flag bucketed for a single one of the
// person's merged distinct IDs. `error` is set (and `result` null) when that ID's
// individual evaluation failed, so one bad ID doesn't blank the whole table.
export interface PerDistinctIdEvaluation {
    distinctId: string
    result: TestResult | null
    error: string | null
}

const EMPTY_FORM: TestFormData = { distinct_id: '', timestamp: '', groups: '' }

// Build the request body for a single evaluation. Shared by the single-ID and
// batch paths so groups/timestamp are parsed and validated identically. Throws on
// invalid groups or timestamp — callers let that fail the loader so the error
// surfaces once via testError rather than per distinct ID.
function buildEvaluationRequest(formData: TestFormData, distinctId: string): FeatureFlagTestEvaluationRequestApi {
    const data: FeatureFlagTestEvaluationRequestApi = {}

    const trimmedDistinctId = distinctId.trim()
    if (trimmedDistinctId) {
        data.distinct_id = trimmedDistinctId
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

    return data
}

// Map an evaluation failure to the user-facing message. Shared by the single-ID
// and batch failure handlers so both surface the same friendly rewrites.
function evaluationErrorMessage(error: string, errorObject?: unknown): string {
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
}

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
        setSelectedPerson: (person: Partial<PersonType> | null, distinctId?: string) => ({ person, distinctId }),
        setIncludeTime: (includeTime: boolean) => ({ includeTime }),
        setSelectedResultDistinctId: (distinctId: string | null) => ({ distinctId }),
        clearTestForm: true,
    }),
    loaders(({ values }) => ({
        resolvedPersonDistinctIds: [
            null as string[] | null,
            {
                resolvePersonDistinctIds: async (distinctId: string) => {
                    const response = await api.persons.list({ distinct_id: distinctId })
                    return response.results[0]?.distinct_ids ?? []
                },
                setSelectedPerson: () => null,
                clearTestForm: () => null,
            },
        ],
        testEvaluation: [
            null as TestResult | null,
            {
                testFlagEvaluation: async ({ flagId, formData }: { flagId: number; formData: TestFormData }) => {
                    const data = buildEvaluationRequest(formData, formData.distinct_id || '')
                    return await featureFlagsTestEvaluationCreate(String(values.currentProjectId), flagId, data)
                },
            },
        ],
        // Batch counterpart to testEvaluation: evaluate every one of a person's merged
        // distinct IDs in one action so their variants can be shown side by side, instead
        // of forcing the user to re-run the single-ID path once per ID.
        allEvaluations: [
            null as PerDistinctIdEvaluation[] | null,
            {
                testAllDistinctIds: async ({
                    flagId,
                    distinctIds,
                    formData,
                }: {
                    flagId: number
                    distinctIds: string[]
                    formData: TestFormData
                }) => {
                    // Parse groups/timestamp once up front. A malformed form throws here and
                    // fails the whole batch loudly (one testError) rather than N identical times.
                    const baseData = buildEvaluationRequest(formData, '')

                    return await Promise.all(
                        distinctIds.map(async (distinctId): Promise<PerDistinctIdEvaluation> => {
                            try {
                                const result = await featureFlagsTestEvaluationCreate(
                                    String(values.currentProjectId),
                                    flagId,
                                    { ...baseData, distinct_id: distinctId }
                                )
                                return { distinctId, result, error: null }
                            } catch (e) {
                                const apiError = e as ApiError
                                return {
                                    distinctId,
                                    result: null,
                                    error: apiError?.detail || apiError?.message || 'Evaluation failed',
                                }
                            }
                        })
                    )
                },
                // Reset when the single-ID path runs or the person/form changes, so a stale
                // batch table never lingers next to an unrelated single result.
                testFlagEvaluation: () => null,
                setTestFormData: () => null,
                setSelectedPerson: () => null,
                clearTestForm: () => null,
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
                testAllDistinctIds: () => null,
                clearTestForm: () => null,
                testFlagEvaluationFailure: (_, { error, errorObject }: { error: string; errorObject?: unknown }) =>
                    evaluationErrorMessage(error, errorObject),
                // A batch failure means the shared form (groups/timestamp) was invalid — the
                // per-ID API errors are caught inside the loader and shown in the table.
                testAllDistinctIdsFailure: (_, { error, errorObject }: { error: string; errorObject?: unknown }) =>
                    evaluationErrorMessage(error, errorObject),
            },
        ],
        testResult: [
            null as TestResult | null,
            {
                testFlagEvaluationSuccess: (_, { testEvaluation }) => testEvaluation,
                testAllDistinctIds: () => null,
                clearTestForm: () => null,
                setTestFormData: () => null,
            },
        ],
        // Which batch row's detailed condition analysis is expanded in the right panel.
        // Null falls back to the first row so a batch run always shows some detail.
        selectedResultDistinctId: [
            null as string | null,
            {
                setSelectedResultDistinctId: (_, { distinctId }) => distinctId,
                testAllDistinctIds: () => null,
                testFlagEvaluation: () => null,
                setTestFormData: () => null,
                clearTestForm: () => null,
                setSelectedPerson: () => null,
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
            null as Partial<PersonType> | null,
            {
                setSelectedPerson: (_, { person }) => person ?? null,
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
    listeners(({ actions, values }) => ({
        setSelectedPerson: ({ person, distinctId }) => {
            // Persons from the recent tab arrive without distinct_ids. Fetch the full
            // person so hasMultipleDistinctIds and the bucketing picker work correctly.
            if (person && !person.distinct_ids?.length) {
                const id = distinctId ?? values.testFormData.distinct_id
                if (id) {
                    actions.resolvePersonDistinctIds(id)
                }
            }
        },
    })),
    selectors({
        // The result currently driving the detail panel (condition analysis + person
        // properties). In batch mode it's the selected row (or the first, if none picked);
        // otherwise it's the single-ID evaluation.
        activeResult: [
            (s) => [s.testResult, s.allEvaluations, s.selectedResultDistinctId],
            (
                single: TestResult | null,
                all: PerDistinctIdEvaluation[] | null,
                selectedId: string | null
            ): TestResult | null => {
                if (all?.length) {
                    const selected = selectedId ? all.find((e) => e.distinctId === selectedId) : undefined
                    return (selected ?? all[0]).result
                }
                return single
            },
        ],
        // True when the person's merged distinct IDs don't all bucket to the same result —
        // the exact divergence that makes runtime evaluation ambiguous. Errored rows are
        // ignored so a single failed ID doesn't read as a disagreement.
        resultsDiverge: [
            (s) => [s.allEvaluations],
            (all: PerDistinctIdEvaluation[] | null): boolean => {
                if (!all?.length) {
                    return false
                }
                const outcomes = new Set(
                    all.filter((e) => e.result).map((e) => JSON.stringify(e.result?.result ?? null))
                )
                return outcomes.size > 1
            },
        ],
        // Get the set of properties used in any condition
        usedProperties: [
            (s) => [s.activeResult],
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
            (s) => [s.activeResult],
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
            (formData: TestFormData): boolean => Boolean(formData.distinct_id?.trim()),
        ],
        // The distinct IDs known for the selected person. For persons from the Persons
        // tab distinct_ids comes directly from the picker. For partial persons (e.g. the
        // recent tab, which carries name + distinct_id only) we fall back to the async
        // lookup in resolvedPersonDistinctIds, which is null while loading and [] when the
        // person turns out to have only one ID.
        personDistinctIds: [
            (s) => [s.selectedPerson, s.resolvedPersonDistinctIds],
            (person: Partial<PersonType> | null, resolved: string[] | null): string[] =>
                person?.distinct_ids ?? resolved ?? [],
        ],
        // A person merged from multiple distinct IDs can bucket into a different
        // rollout/variant depending on which ID is hashed, so the test result may not
        // match what runtime evaluation produces for the same person.
        hasMultipleDistinctIds: [
            (s) => [s.personDistinctIds],
            (distinctIds: string[]): boolean => distinctIds.length > 1,
        ],
        // The distinct ID the backend reports it bucketed against. Null when the API
        // withholds it to avoid leaking distinct IDs to feature_flag:read-only tokens —
        // we must not fall back to the requested ID, which would mislabel the result.
        bucketingDistinctId: [
            (s) => [s.activeResult],
            (result: TestResult | null): string | null => result?.evaluation_distinct_id ?? null,
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
