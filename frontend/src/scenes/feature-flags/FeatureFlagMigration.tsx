import { useCallback, useEffect, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonDialog, LemonSelect, LemonTabs, lemonToast } from '@posthog/lemon-ui'

import { ExternalFeatureFlag, FetchExternalFlagsResponse, featureFlagMigrationApi } from 'lib/api/featureFlagMigration'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'

export enum MigrationProvider {
    LAUNCHDARKLY = 'launchdarkly',
}

export enum MigrationStep {
    PROVIDER_SELECTION = 'provider_selection',
    AUTHENTICATION = 'authentication',
    FLAG_SELECTION = 'flag_selection',
    IMPORT_EXECUTION = 'import_execution',
}

interface MigrationState {
    provider: MigrationProvider | null
    apiKey: string
    projectKey?: string // For LaunchDarkly
    environment?: string // For LaunchDarkly environment selection
    selectedFlags: ExternalFeatureFlag[]
    fetchedFlags: FetchExternalFlagsResponse | null
    isLoading: boolean
    error: string | null
}

export function FeatureFlagMigrationModal({ onClose }: { onClose: () => void }): JSX.Element {
    const [currentStep, setCurrentStep] = useState<MigrationStep>(MigrationStep.PROVIDER_SELECTION)
    const [migrationState, setMigrationState] = useState<MigrationState>({
        provider: MigrationProvider.LAUNCHDARKLY,
        apiKey: '',
        selectedFlags: [],
        fetchedFlags: null,
        isLoading: false,
        error: null,
    })

    // Reset modal state when component mounts (modal opens)
    useEffect(() => {
        // Force reset of all state when modal opens
        setCurrentStep(MigrationStep.PROVIDER_SELECTION)
        setMigrationState({
            provider: MigrationProvider.LAUNCHDARKLY,
            apiKey: '',
            projectKey: '',
            environment: 'production',
            selectedFlags: [],
            fetchedFlags: null,
            isLoading: false,
            error: null,
        })
    }, [])

    const updateMigrationState = (updates: Partial<MigrationState>): void => {
        setMigrationState((prev) => ({ ...prev, ...updates }))
    }

    const handleNext = async (): Promise<void> => {
        switch (currentStep) {
            case MigrationStep.PROVIDER_SELECTION:
                if (migrationState.provider) {
                    setCurrentStep(MigrationStep.AUTHENTICATION)
                }
                break
            case MigrationStep.AUTHENTICATION:
                if (migrationState.apiKey && migrationState.provider) {
                    await fetchExternalFlags()
                }
                break
            case MigrationStep.FLAG_SELECTION:
                setCurrentStep(MigrationStep.IMPORT_EXECUTION)
                break
        }
    }

    const fetchExternalFlags = async (): Promise<void> => {
        if (!migrationState.provider || !migrationState.apiKey) {
            return
        }

        updateMigrationState({ isLoading: true, error: null })

        try {
            const response = await featureFlagMigrationApi.fetchExternalFlags(
                migrationState.provider,
                migrationState.apiKey,
                migrationState.projectKey,
                migrationState.environment || 'production'
            )

            updateMigrationState({
                fetchedFlags: response,
                isLoading: false,
                error: null,
            })

            setCurrentStep(MigrationStep.FLAG_SELECTION)

            if (response.importable_count === 0) {
                lemonToast.warning(
                    `No importable flags found. ${response.non_importable_count} flags have multiple conditions and cannot be imported yet.`
                )
            } else {
                lemonToast.success(`Found ${response.importable_count} importable flags!`)
            }
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to fetch flags'
            updateMigrationState({
                isLoading: false,
                error: errorMessage,
            })
            lemonToast.error(`Failed to fetch flags: ${errorMessage}`)
        }
    }

    const handleBack = (): void => {
        switch (currentStep) {
            case MigrationStep.AUTHENTICATION:
                setCurrentStep(MigrationStep.PROVIDER_SELECTION)
                break
            case MigrationStep.FLAG_SELECTION:
                setCurrentStep(MigrationStep.AUTHENTICATION)
                break
            case MigrationStep.IMPORT_EXECUTION:
                setCurrentStep(MigrationStep.FLAG_SELECTION)
                break
        }
    }

    const renderStepContent = (): JSX.Element => {
        if (currentStep === MigrationStep.PROVIDER_SELECTION) {
            return <ProviderSelectionStep migrationState={migrationState} onUpdate={updateMigrationState} />
        }

        switch (currentStep) {
            case MigrationStep.AUTHENTICATION:
                return <AuthenticationStep migrationState={migrationState} onUpdate={updateMigrationState} />
            case MigrationStep.FLAG_SELECTION:
                return <FlagSelectionStep migrationState={migrationState} onUpdate={updateMigrationState} />
            case MigrationStep.IMPORT_EXECUTION:
                return <ImportExecutionStep migrationState={migrationState} onUpdate={updateMigrationState} />
            default:
                return <div style={{ padding: '20px', border: '1px solid red' }}>Unknown step: {currentStep}</div>
        }
    }

    const getStepTitle = (): string => {
        switch (currentStep) {
            case MigrationStep.PROVIDER_SELECTION:
                return 'Select Provider'
            case MigrationStep.AUTHENTICATION:
                return 'Authentication'
            case MigrationStep.FLAG_SELECTION:
                return 'Select Feature Flags'
            case MigrationStep.IMPORT_EXECUTION:
                return 'Import Results'
            default:
                return 'Feature Flag Migration'
        }
    }

    const canProceed = (): boolean => {
        if (migrationState.isLoading) {
            return false
        }

        switch (currentStep) {
            case MigrationStep.PROVIDER_SELECTION:
                return !!migrationState.provider
            case MigrationStep.AUTHENTICATION:
                return !!migrationState.apiKey.trim()
            case MigrationStep.FLAG_SELECTION:
                return migrationState.selectedFlags.length > 0
            default:
                return false
        }
    }

    return (
        <LemonDialog
            onClose={onClose}
            title={getStepTitle()}
            description="Import feature flags from external providers to PostHog"
            width={800}
            content={renderStepContent()}
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {currentStep !== MigrationStep.PROVIDER_SELECTION && (
                            <LemonButton type="secondary" onClick={handleBack}>
                                Back
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        {currentStep !== MigrationStep.IMPORT_EXECUTION && (
                            <LemonButton
                                type="primary"
                                onClick={handleNext}
                                disabled={!canProceed()}
                                loading={migrationState.isLoading}
                            >
                                {currentStep === MigrationStep.AUTHENTICATION && migrationState.isLoading
                                    ? 'Fetching flags...'
                                    : 'Next'}
                            </LemonButton>
                        )}
                    </div>
                </div>
            }
        />
    )
}

function ProviderSelectionStep({
    migrationState,
    onUpdate,
}: {
    migrationState: MigrationState
    onUpdate: (updates: Partial<MigrationState>) => void
}): JSX.Element {
    const providerOptions = [
        {
            value: MigrationProvider.LAUNCHDARKLY,
            label: 'LaunchDarkly',
            description: 'Import feature flags from LaunchDarkly',
        },
    ]

    return (
        <div className="space-y-4">
            <div>
                <h4 className="text-lg font-semibold mb-2">Choose your feature flag provider</h4>
                <p className="text-muted">
                    Select the external service you want to import feature flags from. We'll guide you through the
                    process of connecting and importing your flags.
                </p>
            </div>

            <div className="space-y-4">
                {providerOptions.map((option) => (
                    <div
                        key={option.value}
                        className={`border rounded p-4 cursor-pointer transition-all ${
                            migrationState.provider === option.value
                                ? 'border-blue-500 bg-blue-50'
                                : 'border-gray-200 hover:border-blue-300'
                        }`}
                        onClick={() => onUpdate({ provider: option.value })}
                    >
                        <div className="flex items-center space-x-3">
                            <input
                                type="radio"
                                checked={migrationState.provider === option.value}
                                onChange={() => onUpdate({ provider: option.value })}
                                className="form-radio"
                            />
                            <div>
                                <div className="font-medium">{option.label}</div>
                                <div className="text-sm text-muted">{option.description}</div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            <div className="bg-info-highlight border border-info rounded p-3">
                <p className="text-sm">
                    <strong>Note:</strong> We currently support LaunchDarkly with more providers coming soon. Flags with
                    multiple percentage rollout rules cannot be imported.
                </p>
            </div>
        </div>
    )
}

function AuthenticationStep({
    migrationState,
    onUpdate,
}: {
    migrationState: MigrationState
    onUpdate: (updates: Partial<MigrationState>) => void
}): JSX.Element {
    const getProviderDisplayName = (provider: MigrationProvider | null): string => {
        switch (provider) {
            case MigrationProvider.LAUNCHDARKLY:
                return 'LaunchDarkly'
            default:
                return 'your provider'
        }
    }

    const getProviderInstructions = (): JSX.Element => {
        switch (migrationState.provider) {
            case MigrationProvider.LAUNCHDARKLY:
                return (
                    <div className="bg-side border rounded p-4">
                        <h5 className="font-semibold mb-2">How to get your LaunchDarkly API token:</h5>
                        <ol className="list-decimal list-inside space-y-1 text-sm">
                            <li>Log in to your LaunchDarkly account</li>
                            <li>Click on your profile in the top right corner</li>
                            <li>Select 'Account settings'</li>
                            <li>Navigate to 'Authorization' tab</li>
                            <li>Click 'Create token' under 'Personal access tokens' or 'Service tokens'</li>
                            <li>Give your token a name and select 'Reader' role (minimum required)</li>
                            <li>Copy the generated token</li>
                        </ol>
                        <div className="mt-2 text-xs text-info">
                            Tip: You can also provide a project key if you have multiple projects (defaults to
                            'default')
                        </div>
                    </div>
                )
            default:
                return <div>Instructions not available for this provider.</div>
        }
    }

    return (
        <div className="space-y-6">
            <div>
                <h4 className="text-lg font-semibold mb-2">
                    Connect to {getProviderDisplayName(migrationState.provider)}
                </h4>
                <p className="text-muted">
                    Enter your API credentials to connect to your external feature flag provider. This information is
                    used only for importing and is not stored permanently.
                </p>
            </div>

            {getProviderInstructions()}

            <div className="space-y-4">
                <div className="space-y-2">
                    <label className="font-medium">API Key</label>
                    <LemonInput
                        type="password"
                        value={migrationState.apiKey}
                        onChange={(value) => onUpdate({ apiKey: value })}
                        placeholder="Enter your LaunchDarkly API token"
                        data-attr="migration-api-key-input"
                    />
                </div>

                {migrationState.provider === MigrationProvider.LAUNCHDARKLY && (
                    <>
                        <div className="space-y-2">
                            <label className="font-medium">Project Key (optional)</label>
                            <LemonInput
                                value={migrationState.projectKey || ''}
                                onChange={(value) => onUpdate({ projectKey: value })}
                                placeholder="Enter your project key (defaults to 'default')"
                                data-attr="migration-project-key-input"
                            />
                            <div className="text-xs text-muted">
                                Leave empty to use the default project. Find your project key in LaunchDarkly dashboard.
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="font-medium">Environment</label>
                            <LemonSelect
                                value={migrationState.environment || 'production'}
                                onChange={(value) => onUpdate({ environment: value })}
                                options={[
                                    { value: 'production', label: 'Production' },
                                    { value: 'test', label: 'Test' },
                                    { value: 'staging', label: 'Staging' },
                                    { value: 'development', label: 'Development' },
                                ]}
                                data-attr="migration-environment-select"
                            />
                            <div className="text-xs text-muted">
                                Select which LaunchDarkly environment to import flags from. Only flags from this
                                environment will be imported.
                            </div>
                        </div>
                    </>
                )}
            </div>

            <div className="bg-info-highlight border border-info rounded p-3">
                <p className="text-sm">
                    <strong>Privacy:</strong> Your API key is used only to fetch feature flag data and is not stored on
                    our servers. The connection is encrypted and secure.
                </p>
            </div>
        </div>
    )
}

function FlagSelectionStep({
    migrationState,
    onUpdate,
}: {
    migrationState: MigrationState
    onUpdate: (updates: Partial<MigrationState>) => void
}): JSX.Element {
    const [activeTab, setActiveTab] = useState<'importable' | 'not-supported'>('importable')
    const [expandedFlags, setExpandedFlags] = useState<Set<string>>(new Set())

    const toggleFlagExpansion = (flagKey: string): void => {
        setExpandedFlags((prev) => {
            const newSet = new Set(prev)
            if (newSet.has(flagKey)) {
                newSet.delete(flagKey)
            } else {
                newSet.add(flagKey)
            }
            return newSet
        })
    }
    if (migrationState.isLoading) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Fetching feature flags</h4>
                    <p className="text-muted">
                        Please wait while we fetch your feature flags from {migrationState.provider}...
                    </p>
                </div>

                <div className="text-center py-8">
                    <Spinner size="large" />
                    <div className="mt-4 text-muted">This may take a few moments...</div>
                </div>
            </div>
        )
    }

    if (!migrationState.fetchedFlags) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Select feature flags to import</h4>
                    <p className="text-muted">
                        Choose which feature flags you want to import from your external provider.
                    </p>
                </div>

                <div className="text-center py-8">
                    <div className="text-muted">No flags data available. Please go back and try again.</div>
                </div>
            </div>
        )
    }

    const { fetchedFlags } = migrationState

    const toggleFlagSelection = (flag: ExternalFeatureFlag): void => {
        const isSelected = migrationState.selectedFlags.some((f) => f.key === flag.key)

        if (isSelected) {
            onUpdate({
                selectedFlags: migrationState.selectedFlags.filter((f) => f.key !== flag.key),
            })
        } else {
            onUpdate({
                selectedFlags: [...migrationState.selectedFlags, flag],
            })
        }
    }

    // Note: toggleAllImportable function removed as it's not currently used in the UI
    // Can be re-added when "Select All" functionality is needed

    return (
        <div className="space-y-6">
            <div>
                <h4 className="text-lg font-semibold mb-2">Select feature flags to import</h4>
                <p className="text-muted">
                    Choose which feature flags you want to import from {migrationState.provider}. Only flags using
                    manual percentage rollout rules (without targeting conditions) can be imported at this time.
                </p>
            </div>

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as 'importable' | 'not-supported')}
                tabs={[
                    {
                        key: 'importable',
                        label: `Importable (${fetchedFlags.importable_count})`,
                        content: (
                            <div className="space-y-3">
                                {!fetchedFlags.importable_flags || fetchedFlags.importable_flags.length === 0 ? (
                                    <div className="text-center py-8 text-muted">No importable flags found</div>
                                ) : (
                                    fetchedFlags.importable_flags.map((flag) => (
                                        <DetailedFlagCard
                                            key={flag.key}
                                            flag={flag}
                                            isSelected={migrationState.selectedFlags.some((f) => f.key === flag.key)}
                                            onToggleSelection={() => toggleFlagSelection(flag)}
                                            isExpanded={expandedFlags.has(flag.key)}
                                            onToggleExpansion={() => toggleFlagExpansion(flag.key)}
                                            provider={migrationState.provider || 'unknown'}
                                        />
                                    ))
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'not-supported',
                        label: `Not supported (${fetchedFlags.non_importable_count})`,
                        content: (
                            <div className="space-y-3">
                                {fetchedFlags.non_importable_flags.length === 0 ? (
                                    <div className="text-center py-8 text-muted">No unsupported flags found</div>
                                ) : (
                                    fetchedFlags.non_importable_flags.map((flag) => (
                                        <DetailedFlagCard
                                            key={flag.key}
                                            flag={flag}
                                            isSelected={false}
                                            onToggleSelection={() => {}} // Disabled
                                            isExpanded={expandedFlags.has(flag.key)}
                                            onToggleExpansion={() => toggleFlagExpansion(flag.key)}
                                            provider={migrationState.provider || 'unknown'}
                                            disabled={true}
                                        />
                                    ))
                                )}
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function ImportExecutionStep({
    migrationState,
}: {
    migrationState: MigrationState
    onUpdate: (updates: Partial<MigrationState>) => void
}): JSX.Element {
    const [importResults, setImportResults] = useState<any>(null)
    const [isImporting, setIsImporting] = useState(false)
    const [importError, setImportError] = useState<string | null>(null)

    const executeImport = useCallback(async (): Promise<void> => {
        if (!migrationState.provider || migrationState.selectedFlags.length === 0) {
            setImportError('No flags selected for import')
            return
        }

        setIsImporting(true)
        setImportError(null)

        try {
            const results = await featureFlagMigrationApi.importFlags(
                migrationState.provider,
                migrationState.selectedFlags,
                migrationState.environment || 'production'
            )

            setImportResults(results)

            if (results.success_count > 0) {
                lemonToast.success(`Successfully imported ${results.success_count} feature flags!`)
            }

            if (results.failure_count > 0) {
                lemonToast.warning(`${results.failure_count} flags failed to import`)
            }
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to import flags'
            setImportError(errorMessage)
            lemonToast.error(`Import failed: ${errorMessage}`)
        } finally {
            setIsImporting(false)
        }
    }, [migrationState.provider, migrationState.selectedFlags, migrationState.environment])

    // Execute import when component mounts
    useEffect(() => {
        if (!importResults && !isImporting && !importError) {
            executeImport()
        }
    }, [importResults, isImporting, importError, executeImport])

    if (isImporting) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Importing feature flags</h4>
                    <p className="text-muted">Please wait while we import your selected feature flags...</p>
                </div>

                <div className="text-center py-12">
                    <Spinner className="text-3xl" />
                    <div className="mt-4 text-muted">
                        Importing {migrationState.selectedFlags.length} flags from {migrationState.provider}
                    </div>
                </div>
            </div>
        )
    }

    if (importError) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Import failed</h4>
                    <p className="text-muted">There was an error importing your feature flags.</p>
                </div>

                <div className="bg-danger-highlight border border-danger rounded p-4">
                    <div className="font-medium text-danger mb-2">Error Details:</div>
                    <div className="text-sm">{importError}</div>
                </div>

                <LemonButton type="secondary" onClick={executeImport}>
                    Retry Import
                </LemonButton>
            </div>
        )
    }

    if (!importResults) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Ready to import</h4>
                    <p className="text-muted">Click the button below to start importing your selected feature flags.</p>
                </div>

                <LemonButton type="primary" onClick={executeImport}>
                    Start Import
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div>
                <h4 className="text-lg font-semibold mb-2">Import complete</h4>
                <p className="text-muted">Review the results of your feature flag import.</p>
            </div>

            <div className="bg-side border rounded p-4">
                <div className="grid grid-cols-3 gap-4 text-center">
                    <div>
                        <div className="text-2xl font-bold text-success">{importResults.success_count}</div>
                        <div className="text-sm text-muted">Successfully imported</div>
                    </div>
                    <div>
                        <div className="text-2xl font-bold text-danger">{importResults.failure_count}</div>
                        <div className="text-sm text-muted">Failed to import</div>
                    </div>
                    <div>
                        <div className="text-2xl font-bold">{migrationState.selectedFlags.length}</div>
                        <div className="text-sm text-muted">Total selected</div>
                    </div>
                </div>
            </div>

            {importResults.imported_flags && importResults.imported_flags.length > 0 && (
                <div>
                    <h5 className="font-medium mb-3 text-success">Successfully Imported Flags</h5>
                    <div className="space-y-2">
                        {importResults.imported_flags.map((item: any, index: number) => (
                            <div key={index} className="bg-success-highlight border border-success rounded p-3">
                                <div className="flex justify-between items-center">
                                    <div>
                                        <div className="font-medium">{item.external_flag.name}</div>
                                        <div className="text-sm text-muted">Key: {item.external_flag.key}</div>
                                    </div>
                                    <div className="text-sm">
                                        <div>PostHog ID: {item.posthog_flag.id}</div>
                                        <div>Status: {item.posthog_flag.active ? 'Active' : 'Inactive'}</div>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {importResults.failed_imports && importResults.failed_imports.length > 0 && (
                <div>
                    <h5 className="font-medium mb-3 text-danger">Failed Imports</h5>
                    <div className="space-y-2">
                        {importResults.failed_imports.map((item: any, index: number) => (
                            <div key={index} className="bg-danger-highlight border border-danger rounded p-3">
                                <div className="font-medium">{item.flag.name}</div>
                                <div className="text-sm text-muted">Key: {item.flag.key}</div>
                                <div className="text-sm text-danger mt-1">Error: {item.error}</div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

interface DetailedFlagCardProps {
    flag: ExternalFeatureFlag
    isSelected: boolean
    onToggleSelection: () => void
    isExpanded: boolean
    onToggleExpansion: () => void
    provider: string
    disabled?: boolean
}

function DetailedFlagCard({
    flag,
    isSelected,
    onToggleSelection,
    isExpanded,
    onToggleExpansion,
    provider,
    disabled = false,
}: DetailedFlagCardProps): JSX.Element {
    return (
        <div className={`border rounded ${disabled ? 'opacity-60 bg-muted/20' : ''}`}>
            <div className="p-3 flex items-start space-x-3 hover:bg-side">
                <LemonCheckbox checked={isSelected} onChange={onToggleSelection} disabled={disabled} />
                <div className="flex-1">
                    {/* Header section */}
                    <div className="flex items-start justify-between">
                        <div className="flex-1">
                            <div className="font-medium">{flag.key}</div>
                            {flag.name && flag.name !== flag.key && (
                                <div className="text-sm text-muted">{flag.name}</div>
                            )}
                            {flag.description && <div className="text-sm text-muted mt-0.5">{flag.description}</div>}
                        </div>
                        <LemonButton size="xsmall" type="secondary" onClick={onToggleExpansion}>
                            {isExpanded ? '↑ Less' : '↓ More'}
                        </LemonButton>
                    </div>

                    {/* Basic info */}
                    <div className="flex items-center space-x-3 mt-1.5">
                        <span
                            className={`px-2 py-0.5 rounded text-xs ${
                                flag.enabled ? 'bg-success-light text-success-dark' : 'bg-muted text-muted-dark'
                            }`}
                        >
                            {flag.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        <span className="text-xs text-muted">
                            {flag.conditions.length} condition{flag.conditions.length !== 1 ? 's' : ''}
                        </span>
                        {flag.variants && flag.variants.length > 0 && (
                            <span className="text-xs text-muted">
                                {flag.variants.length} variant{flag.variants.length !== 1 ? 's' : ''}
                            </span>
                        )}
                    </div>
                    {/* Import Issues - moved to bottom */}
                    {flag.import_issues && flag.import_issues.length > 0 && (
                        <div className="mt-2 text-xs text-warning">⚠ {flag.import_issues.join(', ')}</div>
                    )}

                    {/* Expanded details */}
                    {isExpanded && (
                        <div className="mt-3 space-y-3 border-t pt-3">
                            {/* Compact Metadata */}
                            <div className="flex items-center space-x-4 text-xs text-muted">
                                {flag.metadata?.created_at && (
                                    <span>Created {new Date(flag.metadata.created_at).toLocaleDateString()}</span>
                                )}
                                {flag.metadata?.updated_at && (
                                    <span>Updated {new Date(flag.metadata.updated_at).toLocaleDateString()}</span>
                                )}
                                {flag.metadata?.tags && flag.metadata.tags.length > 0 && (
                                    <span>Tags: {flag.metadata.tags.join(', ')}</span>
                                )}
                            </div>

                            {/* Environment-specific Targeting */}
                            {(() => {
                                return (
                                    (provider === 'launchdarkly' || provider === MigrationProvider.LAUNCHDARKLY) &&
                                    flag.metadata?.environment_configs &&
                                    Object.keys(flag.metadata.environment_configs).length > 0
                                )
                            })() && <EnvironmentTargeting flag={flag} />}

                            {/* Variants - More compact */}
                            {flag.variants && flag.variants.length > 0 && (
                                <div>
                                    <h4 className="font-medium text-sm mb-1.5">Variants</h4>
                                    <div className="flex flex-wrap gap-2">
                                        {flag.variants.map((variant, idx) => (
                                            <div key={idx} className="bg-side rounded px-2 py-1 text-xs">
                                                <span className="font-medium">{variant.name || variant.key}</span>
                                                <span className="text-muted ml-1">
                                                    ={' '}
                                                    <span className="font-mono">
                                                        {typeof variant.value === 'object'
                                                            ? JSON.stringify(variant.value)
                                                            : String(variant.value)}
                                                    </span>
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Import Issues */}
                            {flag.import_issues && flag.import_issues.length > 0 && (
                                <div>
                                    <h4 className="font-medium text-sm mb-1 text-warning">Import Issues</h4>
                                    <ul className="list-disc list-inside space-y-0.5 text-xs text-warning">
                                        {flag.import_issues.map((issue, idx) => (
                                            <li key={idx}>{issue}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

interface EnvironmentTargetingProps {
    flag: ExternalFeatureFlag
}

function EnvironmentTargeting({ flag }: EnvironmentTargetingProps): JSX.Element {
    const environmentConfigs = flag.metadata?.environment_configs || {}

    if (Object.keys(environmentConfigs).length === 0) {
        return (
            <div>
                <h4 className="font-medium text-sm mb-1.5">Environment Targeting</h4>
                <div className="text-xs text-muted">
                    No environment-specific targeting found (configs: {JSON.stringify(Object.keys(environmentConfigs))})
                </div>
            </div>
        )
    }

    const getVariationName = (variationIndex: number): string => {
        if (flag.variants && flag.variants[variationIndex]) {
            return flag.variants[variationIndex].name || flag.variants[variationIndex].key
        }
        return `Variation ${variationIndex}`
    }

    const formatClauseCondition = (clause: any): string => {
        const values = Array.isArray(clause.values) ? clause.values : [clause.values]
        const valueStr = values.length > 1 ? `[${values.join(', ')}]` : String(values[0] || '')
        const negateStr = clause.negate ? 'NOT ' : ''
        return `${clause.attribute} ${negateStr}${clause.operator} ${valueStr}`
    }

    return (
        <div>
            <h4 className="font-medium text-sm mb-1.5">Environment Targeting</h4>
            <div className="space-y-1.5">
                {Object.entries(environmentConfigs).map(([envName, envConfig]) => (
                    <div key={envName} className="bg-side rounded p-2 text-xs">
                        <div className="flex items-center justify-between mb-1.5">
                            <div className="flex items-center space-x-2">
                                <span className="font-medium capitalize">{envName}</span>
                                <span
                                    className={`px-1.5 py-0.5 rounded text-xs ${
                                        envConfig.enabled
                                            ? 'bg-success-light text-success-dark'
                                            : 'bg-muted text-muted-dark'
                                    }`}
                                >
                                    {envConfig.enabled ? 'ON' : 'OFF'}
                                </span>
                            </div>
                            <span className="text-muted">
                                {envConfig.rules_count} rule{envConfig.rules_count !== 1 ? 's' : ''}
                                {envConfig.target_count > 0 &&
                                    ` + ${envConfig.target_count} target${envConfig.target_count !== 1 ? 's' : ''}`}
                            </span>
                        </div>

                        {/* Show detailed rules */}
                        {envConfig.detailed_rules.length > 0 && (
                            <div className="space-y-1">
                                {envConfig.detailed_rules.map((rule, idx) => (
                                    <div key={rule.id || idx} className="bg-border/20 rounded p-1.5">
                                        {rule.description && (
                                            <div className="font-medium text-muted mb-0.5">{rule.description}</div>
                                        )}

                                        {/* Rule conditions */}
                                        {rule.clauses.length > 0 ? (
                                            <div className="space-y-0.5">
                                                {rule.clauses.map((clause, clauseIdx) => (
                                                    <div key={clauseIdx} className="text-muted font-mono text-xs">
                                                        {formatClauseCondition(clause)}
                                                    </div>
                                                ))}
                                            </div>
                                        ) : (
                                            <div className="text-muted">All users</div>
                                        )}

                                        {/* Rollout info */}
                                        {rule.rollout_info && (
                                            <div className="mt-1 pt-1 border-t border-border/30">
                                                {rule.rollout_info.type === 'rollout' &&
                                                rule.rollout_info.variations ? (
                                                    <div className="flex flex-wrap gap-1">
                                                        {rule.rollout_info.variations.map((v, vIdx) => (
                                                            <span
                                                                key={vIdx}
                                                                className="bg-accent/20 px-1 py-0.5 rounded text-xs"
                                                            >
                                                                {getVariationName(v.variation)}: {v.percentage}%
                                                            </span>
                                                        ))}
                                                    </div>
                                                ) : rule.rollout_info.type === 'direct' &&
                                                  rule.rollout_info.variation !== undefined ? (
                                                    <span className="bg-accent/20 px-1 py-0.5 rounded text-xs">
                                                        → {getVariationName(rule.rollout_info.variation)}
                                                    </span>
                                                ) : null}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Fallthrough rule */}
                        {envConfig.fallthrough && (
                            <div className="mt-1.5 pt-1.5 border-t border-border/50">
                                <div className="flex items-center justify-between">
                                    <span className="text-muted italic">Fallthrough (default):</span>
                                    {envConfig.fallthrough.type === 'rollout' && envConfig.fallthrough.variations ? (
                                        <div className="flex gap-1">
                                            {envConfig.fallthrough.variations.map((v, vIdx) => (
                                                <span key={vIdx} className="bg-accent/20 px-1 py-0.5 rounded text-xs">
                                                    {getVariationName(v.variation)}: {v.percentage}%
                                                </span>
                                            ))}
                                        </div>
                                    ) : envConfig.fallthrough.type === 'direct' &&
                                      envConfig.fallthrough.variation !== undefined ? (
                                        <span className="bg-accent/20 px-1 py-0.5 rounded text-xs">
                                            {getVariationName(envConfig.fallthrough.variation)}
                                        </span>
                                    ) : null}
                                </div>
                            </div>
                        )}

                        {/* Show if no rules but environment is configured */}
                        {envConfig.rules_count === 0 && !envConfig.fallthrough && (
                            <div className="text-muted">
                                {envConfig.enabled ? 'Enabled with no targeting rules' : 'Disabled'}
                                {envConfig.off_variation !== undefined && (
                                    <span> (off → {getVariationName(envConfig.off_variation)})</span>
                                )}
                            </div>
                        )}

                        {/* Show remaining rule count */}
                        {envConfig.rules_count > 3 && (
                            <div className="text-muted italic mt-1">+{envConfig.rules_count - 3} more rules...</div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}

// Legacy function - now using state-based modal approach
export function openFeatureFlagMigrationDialog(): void {
    console.warn('openFeatureFlagMigrationDialog is deprecated. Use FeatureFlagMigrationModal component instead.')
}
