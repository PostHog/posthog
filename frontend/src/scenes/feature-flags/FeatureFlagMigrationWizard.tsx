import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

import { LemonButton, LemonTable, LemonInput, LemonSelect, LemonTabs } from '@posthog/lemon-ui'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDropdown } from '@posthog/lemon-ui'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useState } from 'react'

import { ExternalFeatureFlag } from 'lib/api/featureFlagMigration'
import { MigrationProvider, featureFlagMigrationWizardLogic } from './featureFlagMigrationWizardLogic'

import IconStatsig from 'public/services/statsig.com.png'
import IconLaunchDarkly from 'public/services/launchdarkly.com.png'

// Provider logos
const getProviderLogo = (provider: MigrationProvider): string => {
    switch (provider) {
        case MigrationProvider.STATSIG:
            return IconStatsig
        case MigrationProvider.LAUNCHDARKLY:
            return IconLaunchDarkly
        default:
            return ''
    }
}

interface FeatureFlagMigrationWizardProps {
    onComplete?: () => void
}

export function FeatureFlagMigrationWizard({ onComplete }: FeatureFlagMigrationWizardProps): JSX.Element {
    return (
        <BindLogic logic={featureFlagMigrationWizardLogic} props={{ onComplete }}>
            <InternalFeatureFlagMigrationWizard onComplete={onComplete} />
        </BindLogic>
    )
}

function InternalFeatureFlagMigrationWizard({ onComplete }: FeatureFlagMigrationWizardProps): JSX.Element {
    const {
        currentStep,
        isLoading,
        canGoBack,
        canGoNext,
        nextButtonText,
        stepTitle,
        stepDescription,
        selectedProvider,
    } = useValues(featureFlagMigrationWizardLogic)
    const { onBack, onNext, onClear, startNewImport, fetchExternalFlags, extractFieldMappings, executeImport } = useActions(featureFlagMigrationWizardLogic)

    useEffect(() => onClear, [onClear])

    const footer = useCallback(() => {
        if (currentStep === 1) {
            return null
        }

        if (currentStep === 5) {
            // Final step - show different buttons
            return (
                <div className="flex flex-row gap-2 justify-end mt-4">
                    <LemonButton
                        type="secondary"
                        center
                        data-attr="migration-start-new"
                        onClick={startNewImport}
                    >
                        Start New Import
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        center
                        onClick={() => {
                            if (onComplete) {
                                onComplete()
                            } else {
                                // Navigate to feature flags page
                                window.location.href = '/feature_flags'
                            }
                        }}
                        data-attr="migration-go-to-flags"
                    >
                        {nextButtonText}
                    </LemonButton>
                </div>
            )
        }

        return (
            <div className="flex flex-row gap-2 justify-end mt-4">
                <LemonButton
                    type="secondary"
                    center
                    data-attr="migration-back-button"
                    onClick={onBack}
                    disabledReason={!canGoBack ? 'You cant go back from here' : undefined}
                >
                    Back
                </LemonButton>
                <LemonButton
                    loading={isLoading}
                    disabledReason={!canGoNext ? 'Complete current step to continue' : undefined}
                    type="primary"
                    center
                    onClick={() => {
                        if (currentStep === 2) {
                            // Authentication step - fetch flags
                            fetchExternalFlags()
                        } else if (currentStep === 3) {
                            // Flag selection step - extract field mappings
                            extractFieldMappings()
                        } else if (currentStep === 4) {
                            // Field mapping step - execute import
                            executeImport()
                        } else {
                            // Default step advancement
                            onNext()
                        }
                    }}
                    data-attr="migration-next"
                >
                    {nextButtonText}
                </LemonButton>
            </div>
        )
    }, [currentStep, canGoBack, onBack, isLoading, canGoNext, nextButtonText, onNext, onComplete, startNewImport])

    return (
        <div className="space-y-6">
            {selectedProvider && currentStep > 1 && (
                <div className="flex items-center gap-3 mb-4">
                    <ProviderIcon provider={selectedProvider} size="small" />
                    <div>
                        <h4 className="text-lg font-semibold mb-0">{stepTitle}</h4>
                        <p className="text-sm text-muted-alt mb-0">{stepDescription}</p>
                    </div>
                </div>
            )}

            {currentStep === 1 ? (
                <ProviderSelectionStep />
            ) : currentStep === 2 ? (
                <AuthenticationStep />
            ) : currentStep === 3 ? (
                <FlagSelectionStep />
            ) : currentStep === 4 ? (
                <FieldMappingStep />
            ) : currentStep === 5 ? (
                <ImportResultsStep />
            ) : (
                <div>Something went wrong...</div>
            )}

            {footer()}
        </div>
    )
}

function ProviderIcon({ provider, size = 'medium' }: { provider: MigrationProvider; size?: 'small' | 'medium' }): JSX.Element {
    const sizePx = size === 'small' ? 30 : 60
    const logo = getProviderLogo(provider)

    return (
        <img
            src={logo}
            alt={provider}
            height={sizePx}
            width={sizePx}
            className="object-contain max-w-none rounded"
        />
    )
}

function ProviderSelectionStep(): JSX.Element {
    const { selectProvider } = useActions(featureFlagMigrationWizardLogic)

    const providers = [
        {
            key: MigrationProvider.STATSIG,
            name: 'Statsig',
            description: 'Import Feature Gates and Dynamic Configs',
        },
        {
            key: MigrationProvider.LAUNCHDARKLY,
            name: 'LaunchDarkly',
            description: 'Import feature flags from LaunchDarkly',
        },
    ]

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-xl font-semibold mb-2">Import feature flags</h3>
                <p className="text-muted">Choose the external service you want to import feature flags from.</p>
            </div>

            <LemonTable
                dataSource={providers}
                size="small"
                columns={[
                    {
                        title: '',
                        width: 0,
                        render: (_, provider) => (
                            <ProviderIcon provider={provider.key} size="small" />
                        ),
                    },
                    {
                        title: 'Provider',
                        key: 'name',
                        render: (_, provider) => (
                            <LemonTableLink
                                title={provider.name}
                                description={provider.description}
                                onClick={() => selectProvider(provider.key)}
                            />
                        ),
                    },
                    {
                        width: 0,
                        render: (_, provider) => (
                            <LemonButton
                                type="primary"
                                data-attr={`select-${provider.key}`}
                                onClick={() => selectProvider(provider.key)}
                                fullWidth
                            >
                                Select
                            </LemonButton>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function AuthenticationStep(): JSX.Element {
    const { selectedProvider, apiKey, projectKey, environment } = useValues(featureFlagMigrationWizardLogic)
    const { setApiKey, setProjectKey, setEnvironment } = useActions(featureFlagMigrationWizardLogic)

    const getProviderInstructions = (): JSX.Element => {
        switch (selectedProvider) {
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
                    </div>
                )
            case MigrationProvider.STATSIG:
                return (
                    <div className="bg-side border rounded p-4">
                        <h5 className="font-semibold mb-2">How to get your Statsig Console API Key:</h5>
                        <ol className="list-decimal list-inside space-y-1 text-sm">
                            <li>Log in to your Statsig console</li>
                            <li>Navigate to 'Settings' → 'Keys & Environments'</li>
                            <li>Create a new Console API Key by clicking 'Create New Key'</li>
                            <li>Select 'Make Read Only' for security</li>
                            <li>Copy the generated Console API Key</li>
                        </ol>
                        <div className="mt-2 text-xs text-warning">
                            <strong>Important:</strong> Use your Console API Key, not the Client Key or Server Secret Key.
                        </div>
                    </div>
                )
            default:
                return <div>Instructions not available for this provider.</div>
        }
    }

    return (
        <div className="space-y-6">
            {getProviderInstructions()}

            <div className="space-y-4">
                <div className="space-y-2">
                    <label className="font-medium">
                        {selectedProvider === MigrationProvider.STATSIG ? 'Console API Key' : 'API Key'}
                    </label>
                    <LemonInput
                        type="password"
                        value={apiKey}
                        onChange={setApiKey}
                        placeholder={
                            selectedProvider === MigrationProvider.STATSIG
                                ? 'Enter your Statsig Console API Key'
                                : 'Enter your LaunchDarkly API token'
                        }
                        data-attr="migration-api-key-input"
                    />
                </div>

                {selectedProvider === MigrationProvider.LAUNCHDARKLY && (
                    <>
                        <div className="space-y-2">
                            <label className="font-medium">Project Key (optional)</label>
                            <LemonInput
                                value={projectKey}
                                onChange={setProjectKey}
                                placeholder="Enter your project key (defaults to 'default')"
                                data-attr="migration-project-key-input"
                            />
                            <div className="text-xs text-muted">
                                Leave empty to use the default project.
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="font-medium">Environment</label>
                            <LemonSelect
                                value={environment}
                                onChange={setEnvironment}
                                options={[
                                    { value: 'production', label: 'Production' },
                                    { value: 'test', label: 'Test' },
                                    { value: 'staging', label: 'Staging' },
                                    { value: 'development', label: 'Development' },
                                ]}
                                data-attr="migration-environment-select"
                            />
                            <div className="text-xs text-muted">
                                Select which LaunchDarkly environment to import flags from.
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

function FlagSelectionStep(): JSX.Element {
    const { fetchedFlags, selectedFlags, selectedProvider, isLoading } = useValues(featureFlagMigrationWizardLogic)
    const { toggleFlagSelection } = useActions(featureFlagMigrationWizardLogic)
    const [activeTab, setActiveTab] = useState<'importable' | 'not-supported' | 'feature-gates' | 'dynamic-configs'>(
        selectedProvider === MigrationProvider.STATSIG ? 'feature-gates' : 'importable'
    )

    if (isLoading) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Fetching feature flags</h4>
                    <p className="text-muted">
                        Please wait while we fetch your feature flags from {selectedProvider}...
                    </p>
                </div>

                <div className="text-center py-8">
                    <Spinner size="large" />
                    <div className="mt-4 text-muted">This may take a few moments...</div>
                </div>
            </div>
        )
    }

    if (!fetchedFlags) {
        return (
            <div className="space-y-6">
                <div className="text-center py-8">
                    <div className="text-muted">No flags data available. Please go back and try again.</div>
                </div>
            </div>
        )
    }

    const getCurrentFlags = () => {
        if (selectedProvider === MigrationProvider.STATSIG) {
            return activeTab === 'feature-gates'
                ? fetchedFlags.importable_flags.filter((f: ExternalFeatureFlag) => (f.metadata as any)?.statsig_type === 'feature_gate')
                : fetchedFlags.importable_flags.filter((f: ExternalFeatureFlag) => (f.metadata as any)?.statsig_type === 'dynamic_config')
        } else {
            return activeTab === 'importable' ? fetchedFlags.importable_flags : []
        }
    }

    const currentFlags = getCurrentFlags()
    const allCurrentFlagsSelected = currentFlags.length > 0 && currentFlags.every((flag: ExternalFeatureFlag) => selectedFlags.some((selected: ExternalFeatureFlag) => selected.key === flag.key))

    const handleSelectAll = () => {
        if (allCurrentFlagsSelected) {
            // Deselect all current flags
            currentFlags.forEach((flag: ExternalFeatureFlag) => {
                if (selectedFlags.some((selected: ExternalFeatureFlag) => selected.key === flag.key)) {
                    toggleFlagSelection(flag)
                }
            })
        } else {
            // Select all current flags
            currentFlags.forEach((flag: ExternalFeatureFlag) => {
                if (!selectedFlags.some((selected: ExternalFeatureFlag) => selected.key === flag.key)) {
                    toggleFlagSelection(flag)
                }
            })
        }
    }

    return (
        <div className="space-y-6">
            {selectedProvider === MigrationProvider.STATSIG ? (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as any)}
                    tabs={[
                        {
                            key: 'feature-gates',
                            label: `Feature Gates (${fetchedFlags.importable_flags.filter((f: ExternalFeatureFlag) => (f.metadata as any)?.statsig_type === 'feature_gate').length})`,
                            content: (
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center">
                                        <div className="text-sm text-muted">
                                            {selectedFlags.length} of {fetchedFlags.importable_flags.length} selected
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={handleSelectAll}
                                            disabled={currentFlags.length === 0}
                                        >
                                            {allCurrentFlagsSelected ? 'Deselect All' : 'Select All'}
                                        </LemonButton>
                                    </div>
                                    <FlagSelectionTable
                                        flags={currentFlags}
                                        selectedFlags={selectedFlags}
                                        onToggleSelection={toggleFlagSelection}
                                    />
                                </div>
                            ),
                        },
                        {
                            key: 'dynamic-configs',
                            label: `Dynamic Configs (${fetchedFlags.importable_flags.filter((f: ExternalFeatureFlag) => (f.metadata as any)?.statsig_type === 'dynamic_config').length})`,
                            content: (
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center">
                                        <div className="text-sm text-muted">
                                            {selectedFlags.length} of {fetchedFlags.importable_flags.length} selected
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={handleSelectAll}
                                            disabled={currentFlags.length === 0}
                                        >
                                            {allCurrentFlagsSelected ? 'Deselect All' : 'Select All'}
                                        </LemonButton>
                                    </div>
                                    <FlagSelectionTable
                                        flags={currentFlags}
                                        selectedFlags={selectedFlags}
                                        onToggleSelection={toggleFlagSelection}
                                    />
                                </div>
                            ),
                        },
                    ]}
                />
            ) : (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as 'importable' | 'not-supported')}
                    tabs={[
                        {
                            key: 'importable',
                            label: `Importable (${fetchedFlags.importable_count})`,
                            content: (
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center">
                                        <div className="text-sm text-muted">
                                            {selectedFlags.length} of {fetchedFlags.importable_flags.length} selected
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={handleSelectAll}
                                            disabled={fetchedFlags.importable_flags.length === 0}
                                        >
                                            {allCurrentFlagsSelected ? 'Deselect All' : 'Select All'}
                                        </LemonButton>
                                    </div>
                                    <FlagSelectionTable
                                        flags={fetchedFlags.importable_flags}
                                        selectedFlags={selectedFlags}
                                        onToggleSelection={toggleFlagSelection}
                                    />
                                </div>
                            ),
                        },
                        {
                            key: 'not-supported',
                            label: `Not supported (${fetchedFlags.non_importable_count})`,
                            content: (
                                <FlagSelectionTable
                                    flags={fetchedFlags.non_importable_flags}
                                    selectedFlags={[]}
                                    onToggleSelection={() => {}} // Disabled
                                    disabled={true}
                                />
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}

function FieldMappingStep(): JSX.Element {
    const { fieldMappings, originalFieldMappings, selectedMappingsCount, isLoading } = useValues(featureFlagMigrationWizardLogic)
    const { updateFieldMapping, resetFieldMappings } = useActions(featureFlagMigrationWizardLogic)

    if (isLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner className="mr-3" />
                <span>Extracting field mappings from selected flags...</span>
            </div>
        )
    }


    return (
        <div className="space-y-6">
            <div>
                {fieldMappings.length === 0 ? (
                    <div className="text-center py-8">
                        <div className="bg-success/10 border border-success/20 rounded-lg p-4 max-w-md mx-auto">
                            <p className="text-sm text-success-foreground">
                                ✓ All fields are ready for import.
                            </p>
                        </div>
                    </div>
                ) : (
                    <>
                        <div className={`border rounded-lg p-3 mb-4 ${
                            selectedMappingsCount < fieldMappings.length
                                ? 'bg-warning/10 border-warning/20'
                                : 'bg-success/10 border-success/20'
                        }`}>
                            <div className="flex justify-between items-center">
                                <div className="text-sm">
                                    <strong>{selectedMappingsCount}</strong> of{' '}
                                    <strong>{fieldMappings.length}</strong> fields mapped
                                    {selectedMappingsCount < fieldMappings.length && (
                                        <div className="mt-1 text-warning-foreground">
                                            <strong>{fieldMappings.length - selectedMappingsCount}</strong> unmapped fields highlighted below -
                                            these will be skipped during import and related rules will be ignored
                                        </div>
                                    )}
                                </div>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => resetFieldMappings(originalFieldMappings)}
                                    disabled={fieldMappings.length === 0}
                                >
                                    Reset
                                </LemonButton>
                            </div>
                        </div>

                        <LemonTable
                            dataSource={fieldMappings}
                            onRow={(mapping) => ({
                                className: !mapping.posthog_field && !(mapping.auto_selected && mapping.external_type === 'segment')
                                    ? 'bg-warning/10 border-l-4 border-l-warning'
                                    : ''
                            })}
                            columns={[
                                {
                                    title: 'External Field',
                                    key: 'external_field',
                                    render: (_, mapping) => (
                                        <div className="flex items-center gap-2">
                                            {!mapping.posthog_field && !(mapping.auto_selected && mapping.external_type === 'segment') && (
                                                <div className="w-2 h-2 bg-warning rounded-full flex-shrink-0" title="Unmapped field" />
                                            )}
                                            <div className="flex-1">
                                            <div className="font-medium text-sm">{mapping.display_name}</div>
                                            <div className="text-xs text-muted-foreground">
                                                <code>{mapping.external_key}</code> ({mapping.external_type})
                                            </div>
                                            </div>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Map to PostHog Field',
                                    key: 'mapping',
                                    render: (_, mapping) => (
                                        <div className="w-full py-2">
                                            {mapping.external_type === 'segment' ? (
                                                <div className="text-sm text-muted-foreground py-2">
                                                    Segments are automatically converted to cohorts during import
                                                </div>
                                            ) : (
                                                <PropertySelector
                                                    value={mapping.posthog_field || ''}
                                                    onChange={(value) => {
                                                        updateFieldMapping(
                                                            mapping.external_key,
                                                            value,
                                                            'person'
                                                        )
                                                    }}
                                                    placeholder="Choose PostHog field..."
                                                />
                                            )}
                                        </div>
                                    ),
                                },
                            ]}
                            pagination={undefined}
                            size="small"
                        />
                    </>
                )}
            </div>
        </div>
    )
}

function ImportResultsStep(): JSX.Element {
    const { importResults } = useValues(featureFlagMigrationWizardLogic)

    if (!importResults) {
        return (
            <div className="space-y-6">
                <div>
                    <h4 className="text-lg font-semibold mb-2">Ready to import</h4>
                    <p className="text-muted">Click the button to start importing your selected feature flags.</p>
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-6">

            {importResults.imported_flags && importResults.imported_flags.length > 0 && (
                <div>
                    <h5 className="font-medium mb-3 text-success">Successfully Imported Flags</h5>
                    <LemonTable
                        dataSource={importResults.imported_flags}
                        columns={[
                            {
                                title: 'Key',
                                dataIndex: 'posthog_flag',
                                key: 'key',
                                render: (posthog_flag: any) => (
                                    <span>{posthog_flag.key}</span>
                                ),
                            },
                            {
                                title: 'Name',
                                dataIndex: 'external_flag',
                                key: 'name',
                                render: (external_flag: any) => (
                                    <div>{external_flag.name || '—'}</div>
                                ),
                            },
                            {
                                title: 'PostHog ID',
                                dataIndex: 'posthog_flag',
                                key: 'id',
                                render: (posthog_flag: any) => (
                                    <span>{posthog_flag.id}</span>
                                ),
                            },
                            {
                                title: 'Actions',
                                key: 'actions',
                                render: (_, item: any) => (
                                    <div className="py-2">
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={() => window.open(`/feature_flags/${item.posthog_flag.id}`, '_blank')}
                                        >
                                                View Flag
                                        </LemonButton>
                                    </div>
                                ),
                            },
                        ]}
                        pagination={undefined}
                        size="small"
                        className="border border-danger/20"
                    />
                </div>
            )}

            {importResults.failed_imports && importResults.failed_imports.length > 0 && (
                <div>
                    <h5 className="font-medium mb-3 text-danger">Failed to Import</h5>
                    <LemonTable
                        dataSource={importResults.failed_imports}
                        columns={[
                            {
                                title: 'Key',
                                dataIndex: 'flag',
                                key: 'key',
                                render: (flag: any) => (
                                    <span>{flag.key}</span>
                                ),
                            },
                            {
                                title: 'Name',
                                dataIndex: 'flag',
                                key: 'name',
                                render: (flag: any) => (
                                    <div>{flag.name || '—'}</div>
                                ),
                            },
                            {
                                title: 'Reason',
                                dataIndex: 'error',
                                key: 'error',
                                render: (error: string) => (
                                    <div className="text-sm text-danger-foreground">
                                        <div className="flex items-start gap-2">
                                            <span className="text-danger">⚠</span>
                                            <span>{error}</span>
                                        </div>
                                    </div>
                                ),
                            },
                        ]}
                        pagination={undefined}
                        size="small"
                        className="border border-danger/20"
                    />
                </div>
            )}
        </div>
    )
}

// Helper components
function PropertySelector({
    value,
    onChange,
    placeholder,
}: {
    value: string
    onChange: (value: string) => void
    placeholder: string
}): JSX.Element {
    const [dropdownOpen, setDropdownOpen] = useState(false)

    const taxonomicFilter = (
        <TaxonomicFilter
            groupType={value ? TaxonomicFilterGroupType.PersonProperties : undefined}
            value={value}
            onChange={(_, selectedValue) => {
                if (selectedValue) {
                    onChange(selectedValue as string)
                }
                setDropdownOpen(false)
            }}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.FeatureFlags,
            ]}
        />
    )

    const buttonContent = value ? (
        <PropertyKeyInfo
            value={value}
            disablePopover
            ellipsis
            type={TaxonomicFilterGroupType.PersonProperties}
        />
    ) : (
        placeholder
    )

    return (
        <div className="w-full">
            <div className="flex gap-2">
                <LemonDropdown
                    overlay={taxonomicFilter}
                    placement="bottom-start"
                    visible={dropdownOpen}
                    onClickOutside={() => setDropdownOpen(false)}
                >
                    <LemonButton
                        type="secondary"
                        onClick={() => setDropdownOpen(!dropdownOpen)}
                        size="small"
                        className="flex-1 justify-start"
                        sideIcon={null}
                    >
                        {buttonContent}
                    </LemonButton>
                </LemonDropdown>
                {value && (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={() => onChange('')}
                        className="shrink-0"
                    >
                        Clear
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function FlagSelectionTable({
    flags,
    selectedFlags,
    onToggleSelection,
    disabled = false,
}: {
    flags: ExternalFeatureFlag[]
    selectedFlags: ExternalFeatureFlag[]
    onToggleSelection: (flag: ExternalFeatureFlag) => void
    disabled?: boolean
}): JSX.Element {
    return (
        <LemonTable
            dataSource={flags}
            onRow={(flag) => ({
                onClick: (event) => {
                    // Don't toggle selection if clicking on expand button or other interactive elements
                    const target = event.target as HTMLElement
                    if (target.closest('.LemonTable__toggle') || target.closest('button') || target.closest('input')) {
                        return
                    }
                    if (!disabled) {
                        onToggleSelection(flag)
                    }
                },
                style: { cursor: disabled ? 'default' : 'pointer' },
                className: disabled ? '' : 'hover:bg-side'
            })}
            columns={[
                {
                    title: '',
                    key: 'select',
                    width: 40,
                    render: (_, flag) => (
                        <input
                            type="checkbox"
                            checked={selectedFlags.some((f) => f.key === flag.key)}
                            onChange={() => !disabled && onToggleSelection(flag)}
                            disabled={disabled}
                        />
                    ),
                },
                {
                    title: 'Key',
                    key: 'name',
                    render: (_, flag) => (
                        <div>
                            <div className="font-medium">{flag.key}</div>
                        </div>
                    ),
                },
                {
                    title: 'Name',
                    key: 'name',
                    render: (_, flag) => (
                        <div>
                            <div className="font-medium">{flag.name || '-'}</div>
                        </div>
                    ),
                },
                {
                    title: 'Description',
                    key: 'description',
                    render: (_, flag) => (
                        <div className="text-sm">
                            {flag.description || '—'}
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    width: 100,
                    render: (_, flag) => (
                        <span className={`text-xs px-2 py-0.5 rounded ${flag.enabled ? 'bg-success/10 text-success' : 'bg-muted/10 text-muted'}`}>
                            {flag.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    ),
                },
                {
                    title: 'Conditions',
                    key: 'conditions',
                    width: 100,
                    render: (_, flag) => (
                        <span className="text-sm text-muted">
                            {flag.conditions.length} condition{flag.conditions.length !== 1 ? 's' : ''}
                        </span>
                    ),
                },
            ]}
            expandable={{
                expandedRowRender: function RenderFlagDetails(flag) {
                    return (
                        <div className="p-4 bg-side border rounded">
                            <div className="space-y-3">
                                <div>
                                    <h5 className="font-medium mb-2">Flag Details</h5>
                                    <div className="grid grid-cols-2 gap-4 text-sm">
                                        <div>
                                            <span className="text-muted">Key:</span> <code>{flag.key}</code>
                                        </div>
                                        {flag.name && flag.name !== flag.key && (
                                            <div>
                                                <span className="text-muted">Name:</span> {flag.name}
                                            </div>
                                        )}
                                        <div>
                                            <span className="text-muted">Status:</span> {flag.enabled ? 'Enabled' : 'Disabled'}
                                        </div>
                                        <div>
                                            <span className="text-muted">Conditions:</span> {flag.conditions.length}
                                        </div>
                                    </div>
                                </div>

                                {flag.conditions.length > 0 && (
                                    <div>
                                        <h5 className="font-medium mb-2">Conditions</h5>
                                        <div className="space-y-2">
                                            {flag.conditions.map((condition, index) => (
                                                <div key={index} className="text-sm bg-white border rounded p-2">
                                                    <div className="font-medium mb-1">Condition {index + 1}</div>
                                                    <pre className="text-xs text-muted whitespace-pre-wrap overflow-auto">
                                                        {JSON.stringify(condition, null, 2)}
                                                    </pre>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {flag.metadata && (
                                    <div>
                                        <h5 className="font-medium mb-2">Metadata</h5>
                                        <pre className="text-xs text-muted bg-white border rounded p-2 whitespace-pre-wrap overflow-auto">
                                            {JSON.stringify(flag.metadata, null, 2)}
                                        </pre>
                                    </div>
                                )}
                            </div>
                        </div>
                    )
                },
                rowExpandable: () => true,
                noIndent: true,
            }}
            size="small"
        />
    )
}