import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { lemonToast } from '@posthog/lemon-ui'
import { ExternalFeatureFlag, FetchExternalFlagsResponse, featureFlagMigrationApi } from 'lib/api/featureFlagMigration'

export enum MigrationProvider {
    LAUNCHDARKLY = 'launchdarkly',
    STATSIG = 'statsig',
}

interface FieldMapping {
    external_key: string
    external_type: string
    display_name: string
    posthog_field: string | null
    posthog_type: string
    auto_selected: boolean
    options: Array<{ key: string; label: string; type: string }>
}


export const featureFlagMigrationWizardLogic = kea([
    path(['scenes', 'feature-flags', 'featureFlagMigrationWizardLogic']),

    actions({
        // Step navigation
        onNext: true,
        onBack: true,
        onClear: true,

        // Provider selection
        selectProvider: (provider) => ({ provider }),

        // Authentication
        setApiKey: (apiKey) => ({ apiKey }),
        setProjectKey: (projectKey) => ({ projectKey }),
        setEnvironment: (environment) => ({ environment }),

        // Flag fetching
        fetchExternalFlags: true,
        fetchExternalFlagsSuccess: (response) => ({ response }),
        fetchExternalFlagsFailure: (error) => ({ error }),

        // Flag selection
        toggleFlagSelection: (flag) => ({ flag }),

        // Field mapping
        extractFieldMappings: true,
        extractFieldMappingsSuccess: (fieldMappings) => ({ fieldMappings }),
        extractFieldMappingsFailure: (error) => ({ error }),
        updateFieldMapping: (externalKey, posthogField, posthogType) => ({
            externalKey,
            posthogField,
            posthogType
        }),
        resetFieldMappings: (originalMappings) => ({ originalMappings }),
        startNewImport: true,

        // Import execution
        executeImport: true,
        executeImportSuccess: (results) => ({ results }),
        executeImportFailure: (error) => ({ error }),

    }),

    reducers({
        currentStep: [
            1,
            {
                onNext: (state) => state + 1,
                onBack: (state) => Math.max(1, state - 1),
                onClear: () => 1,
                startNewImport: () => 1,
                selectProvider: () => 2, // Auto-advance to authentication
                fetchExternalFlagsSuccess: () => 3, // Auto-advance to flag selection
                extractFieldMappingsSuccess: () => 4, // Auto-advance to field mapping
                executeImportSuccess: () => 5, // Auto-advance to results
            },
        ],

        selectedProvider: [
            null as MigrationProvider | null,
            {
                selectProvider: (_, { provider }) => provider,
                onClear: () => null,
                startNewImport: () => null,
            },
        ],

        apiKey: [
            '',
            {
                setApiKey: (_, { apiKey }) => apiKey,
                onClear: () => '',
                startNewImport: () => '',
            },
        ],

        projectKey: [
            '',
            {
                setProjectKey: (_, { projectKey }) => projectKey,
                onClear: () => '',
                startNewImport: () => '',
            },
        ],

        environment: [
            'production',
            {
                setEnvironment: (_, { environment }) => environment,
                onClear: () => 'production',
                startNewImport: () => 'production',
            },
        ],

        fetchedFlags: [
            null as FetchExternalFlagsResponse | null,
            {
                fetchExternalFlagsSuccess: (_, { response }) => response,
                onClear: () => null,
            },
        ],

        selectedFlags: [
            [] as ExternalFeatureFlag[],
            {
                toggleFlagSelection: (state, { flag }) => {
                    const isSelected = state.some((f: ExternalFeatureFlag) => f.key === flag.key)
                    if (isSelected) {
                        return state.filter((f: ExternalFeatureFlag) => f.key !== flag.key)
                    } else {
                        return [...state, flag]
                    }
                },
                onClear: () => [],
            },
        ],

        fieldMappings: [
            [] as FieldMapping[],
            {
                extractFieldMappingsSuccess: (_, { fieldMappings }) => fieldMappings,
                updateFieldMapping: (state, { externalKey, posthogField, posthogType }) => {
                    return state.map((mapping: FieldMapping) =>
                        mapping.external_key === externalKey
                            ? { ...mapping, posthog_field: posthogField, posthog_type: posthogType }
                            : mapping
                    )
                },
                resetFieldMappings: (state, { originalMappings }) => {
                    return originalMappings && originalMappings.length > 0 ? [...originalMappings] : state
                },
                onClear: () => [],
            },
        ],

        originalFieldMappings: [
            [] as FieldMapping[],
            {
                extractFieldMappingsSuccess: (_, { fieldMappings }) => fieldMappings,
                onClear: () => [],
            },
        ],

        importResults: [
            null as any,
            {
                executeImportSuccess: (_, { results }) => results,
                onClear: () => null,
            },
        ],

        isLoading: [
            false,
            {
                fetchExternalFlags: () => true,
                fetchExternalFlagsSuccess: () => false,
                fetchExternalFlagsFailure: () => false,
                extractFieldMappings: () => true,
                extractFieldMappingsSuccess: () => false,
                extractFieldMappingsFailure: () => false,
                executeImport: () => true,
                executeImportSuccess: () => false,
                executeImportFailure: () => false,
            },
        ],

        error: [
            null as string | null,
            {
                fetchExternalFlagsFailure: (_, { error }) => error,
                extractFieldMappingsFailure: (_, { error }) => error,
                executeImportFailure: (_, { error }) => error,
                fetchExternalFlags: () => null,
                extractFieldMappings: () => null,
                executeImport: () => null,
                onClear: () => null,
            },
        ],
    }),

    selectors({
        canGoBack: [
            (s) => [s.currentStep],
            (currentStep: number): boolean => currentStep > 1,
        ],

        canGoNext: [
            (s) => [s.currentStep, s.selectedProvider, s.apiKey, s.selectedFlags, s.isLoading],
            (currentStep: number, selectedProvider: MigrationProvider | null, apiKey: string, selectedFlags: ExternalFeatureFlag[], isLoading: boolean): boolean => {
                if (isLoading) return false

                switch (currentStep) {
                    case 1: // Provider selection
                        return !!selectedProvider
                    case 2: // Authentication
                        return !!apiKey.trim()
                    case 3: // Flag selection
                        return selectedFlags.length > 0
                    case 4: // Field mapping
                        return true // Always allow proceeding from field mapping
                    default:
                        return false
                }
            },
        ],

        nextButtonText: [
            (s) => [s.currentStep],
            (currentStep: number): string => {
                switch (currentStep) {
                    case 1:
                        return 'Next'
                    case 2:
                        return 'Fetch Feature Flags'
                    case 3:
                        return 'Continue to Field Mapping'
                    case 4:
                        return 'Execute Import'
                    case 5:
                        return 'Go to Feature Flags'
                    default:
                        return 'Next'
                }
            },
        ],

        stepTitle: [
            (s) => [s.currentStep, s.selectedProvider],
            (currentStep: number, selectedProvider: MigrationProvider | null): string => {
                switch (currentStep) {
                    case 1:
                        return 'Import feature flags'
                    case 2:
                        return `Connect to ${selectedProvider === MigrationProvider.STATSIG ? 'Statsig' : 'LaunchDarkly'}`
                    case 3:
                        return 'Select feature flags'
                    case 4:
                        return 'Map Statsig fields to PostHog fields'
                    case 5:
                        return 'Import results'
                    default:
                        return 'Feature flag migration'
                }
            },
        ],

        stepDescription: [
            (s) => [s.currentStep, s.selectedProvider],
            (currentStep: number, selectedProvider: MigrationProvider | null): string => {
                switch (currentStep) {
                    case 1:
                        return 'Choose the external service you want to import feature flags from.'
                    case 2:
                        return `Enter your API credentials to connect to ${selectedProvider === MigrationProvider.STATSIG ? 'Statsig' : 'LaunchDarkly'}.`
                    case 3:
                        return 'Select the feature flags you want to import into PostHog.'
                    case 4:
                        return 'The following fields are used in your selected flags. Choose how they should map to PostHog properties.'
                    case 5:
                        return 'Review your import results.'
                    default:
                        return ''
                }
            },
        ],

        selectedMappingsCount: [
            (s) => [s.fieldMappings],
            (fieldMappings: FieldMapping[]): number => {
                return fieldMappings.filter(mapping => mapping.auto_selected || mapping.posthog_field).length
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        fetchExternalFlags: async () => {
            if (!values.selectedProvider || !values.apiKey) {
                actions.fetchExternalFlagsFailure('Provider and API key are required')
                return
            }

            try {
                const response = await featureFlagMigrationApi.fetchExternalFlags(
                    values.selectedProvider,
                    values.apiKey,
                    values.projectKey,
                    values.environment
                )

                actions.fetchExternalFlagsSuccess(response)

                if (response.importable_count === 0) {
                    lemonToast.warning(
                        `No importable flags found. ${response.non_importable_count} flags have multiple conditions and cannot be imported yet.`
                    )
                } else {
                    lemonToast.success(`Found ${response.importable_count} importable flags!`)
                }
            } catch (error) {
                const errorMessage = error instanceof Error ? error.message : 'Failed to fetch flags'
                actions.fetchExternalFlagsFailure(errorMessage)
                lemonToast.error(`Failed to fetch flags: ${errorMessage}`)
            }
        },

        extractFieldMappings: async () => {
            if (!values.selectedProvider || values.selectedFlags.length === 0) {
                actions.extractFieldMappingsSuccess([])
                return
            }

            try {
                const response = await featureFlagMigrationApi.extractFieldMappings({
                    provider: values.selectedProvider,
                    selected_flags: values.selectedFlags,
                })

                actions.extractFieldMappingsSuccess(response.field_mappings || [])

                if (response.total_fields === 0) {
                    lemonToast.info('No custom fields found in selected flags.')
                } else {
                    lemonToast.success(`Found ${response.total_fields} fields to map!`)
                }
            } catch (error) {
                const errorMessage = error instanceof Error ? error.message : 'Failed to extract field mappings'
                actions.extractFieldMappingsFailure(errorMessage)
                lemonToast.error(`Failed to extract field mappings: ${errorMessage}`)
            }
        },


        executeImport: async () => {
            if (!values.selectedProvider || values.selectedFlags.length === 0) {
                actions.executeImportFailure('No flags selected for import')
                return
            }

            try {
                // Convert field mappings to the format expected by the backend
                const fieldMappingsForImport = values.fieldMappings.reduce(
                    (acc: Record<string, any>, mapping: FieldMapping) => {
                        if (mapping.posthog_field) {
                            acc[mapping.external_key] = {
                                posthog_field: mapping.posthog_field,
                                posthog_type: mapping.posthog_type,
                            }
                        }
                        return acc
                    },
                    {} as Record<string, any>
                )

                const results = await featureFlagMigrationApi.importFlags(
                    values.selectedProvider,
                    values.selectedFlags,
                    values.environment,
                    fieldMappingsForImport
                )

                actions.executeImportSuccess(results)

                if (results.success_count > 0) {
                    lemonToast.success(`Successfully imported ${results.success_count} feature flags!`)
                }

                if (results.failure_count > 0) {
                    lemonToast.warning(`${results.failure_count} flags failed to import`)
                }
            } catch (error) {
                const errorMessage = error instanceof Error ? error.message : 'Failed to import flags'
                actions.executeImportFailure(errorMessage)
                lemonToast.error(`Import failed: ${errorMessage}`)
            }
        },
    })),
])