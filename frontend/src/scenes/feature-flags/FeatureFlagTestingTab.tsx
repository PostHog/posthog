import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonBanner, LemonLabel, LemonCalendarSelectInput, LemonTable } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import type { Dayjs } from 'lib/dayjs'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import type { FeatureFlagType, PersonType } from '~/types'

import { featureFlagsLogic } from './featureFlagsLogic'

export function FeatureFlagTestingTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const {
        testFormData: formData,
        testError: error,
        testResult: result,
        showAllProperties,
        datePickerOpen,
        datePickerValue,
        testEvaluationLoading: isLoading,
    } = useValues(featureFlagsLogic)

    const {
        setTestFormData,
        setTestError,
        setTestResult,
        setShowAllProperties,
        setDatePickerOpen,
        setDatePickerValue,
        clearTestForm,
        testFlagEvaluation,
    } = useActions(featureFlagsLogic)

    const [selectedPerson, setSelectedPerson] = useState<PersonType | null>(null)

    // Clear testing state when feature flag changes
    useEffect(() => {
        clearTestForm()
        setTestError(null)
        setTestResult(null)
        setShowAllProperties(false)
        setSelectedPerson(null)
    }, [featureFlag.id])

    const formatPropertyKey = (key: string): string => {
        return key
            .split('_')
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ')
    }

    const formatPropertyValue = (value: any): string => {
        if (value === null || value === undefined) {
            return 'not set'
        }
        if (typeof value === 'string') {
            return value
        }
        if (typeof value === 'boolean') {
            return value ? 'true' : 'false'
        }
        if (typeof value === 'number') {
            return value.toString()
        }
        if (Array.isArray(value)) {
            return value.map((v) => formatPropertyValue(v)).join(', ')
        }
        if (typeof value === 'object') {
            return JSON.stringify(value)
        }
        return String(value)
    }

    const getUsedProperties = (): Set<string> => {
        const used = new Set<string>()
        if (result?.conditions) {
            result.conditions.forEach((condition) => {
                condition.properties.forEach((prop) => {
                    used.add(prop.key)
                })
            })
        }
        return used
    }

    const handleSubmit = async (): Promise<void> => {
        // Validate that a person is selected
        if (!selectedPerson || !formData.person_id?.trim()) {
            setTestError('Please select a person')
            return
        }

        try {
            // Use person_id as the identifier since it's more stable than distinct_id
            await testFlagEvaluation({ flagId: featureFlag.id, formData })
        } catch {
            // Error handling is done in the kea logic
        }
    }

    const handleClear = (): void => {
        clearTestForm()
        setDatePickerValue(null)
        setTestError(null)
        setTestResult(null)
        setShowAllProperties(false)
        setSelectedPerson(null)
    }

    return (
        <div className="space-y-6">
            <div>
                <h3 className="font-semibold">Test flag evaluation</h3>
                <p className="text-muted">
                    Test how this feature flag evaluates for a specific user, optionally at a historical timestamp.
                    Provides detailed explanations of why the flag matched or didn't match.
                </p>
            </div>

            <div className="flex gap-6">
                {/* Left Panel - Form */}
                <div className="flex-1 space-y-4 max-w-md bg-bg-light p-6 rounded-lg border">
                    <h4 className="font-semibold">Test Parameters</h4>

                    {/* User Selection */}
                    <div className="space-y-3">
                        <LemonLabel>Select Person</LemonLabel>
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.Persons}
                            value={selectedPerson ? selectedPerson.distinct_ids[0] : ''}
                            onChange={(_, __, person) => {
                                if (person) {
                                    setSelectedPerson(person as PersonType)
                                    setTestFormData({
                                        person_id: person.uuid || '',
                                    })
                                } else {
                                    setSelectedPerson(null)
                                    setTestFormData({
                                        person_id: '',
                                    })
                                }
                            }}
                            groupTypes={[TaxonomicFilterGroupType.Persons]}
                            placeholder="Search for a person by name, email, or ID..."
                            allowClear
                            fullWidth
                            renderValue={() => {
                                if (selectedPerson) {
                                    return (
                                        <span>
                                            {selectedPerson.name || selectedPerson.distinct_ids[0] || 'Unknown person'}
                                        </span>
                                    )
                                }
                                return null
                            }}
                        />
                        <p className="text-xs text-muted">
                            Search and select a person from your PostHog instance. You can search by name, email, or
                            distinct ID.
                        </p>

                        {selectedPerson && (
                            <div className="text-xs text-muted space-y-1 p-2 bg-bg-3000 rounded">
                                <div>
                                    <strong>Person ID:</strong> {formData.person_id || 'Not available'}
                                </div>
                                <div>
                                    <strong>Distinct IDs:</strong> {selectedPerson.distinct_ids?.slice(0, 3).join(', ')}
                                    {selectedPerson.distinct_ids &&
                                        selectedPerson.distinct_ids.length > 3 &&
                                        ` (+${selectedPerson.distinct_ids.length - 3} more)`}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Optional Timestamp */}
                    <div className="space-y-3">
                        <LemonLabel>Historical timestamp (optional)</LemonLabel>
                        <LemonCalendarSelectInput
                            value={datePickerValue}
                            format="YYYY-MM-DD HH:mm:ss"
                            visible={datePickerOpen}
                            onClickOutside={() => setDatePickerOpen(false)}
                            onChange={(selectedDate: Dayjs | null) => {
                                setDatePickerValue(selectedDate)
                                const timestamp = selectedDate ? selectedDate.toISOString() : ''
                                setTestFormData({
                                    timestamp,
                                })
                                setDatePickerOpen(false)
                            }}
                            onClose={() => setDatePickerOpen(false)}
                            granularity="minute"
                            clearable={true}
                            buttonProps={{
                                fullWidth: true,
                                onClick: () => setDatePickerOpen(true),
                                children: datePickerValue
                                    ? datePickerValue.format('YYYY-MM-DD HH:mm:ss')
                                    : 'Select date and time',
                            }}
                            showTimeToggle
                            placeholder="Select date and time"
                        />
                        <p className="text-xs text-muted">
                            If provided, evaluates the flag using person properties as they existed at this time. The
                            flag conditions themselves are always current.
                        </p>
                    </div>

                    {/* Optional Groups */}
                    <div className="space-y-3">
                        <LemonLabel>Groups (optional)</LemonLabel>
                        <CodeEditor
                            className="border"
                            language="json"
                            value={formData.groups || '{}'}
                            onChange={(value) => setTestFormData({ groups: value || '' })}
                            height={100}
                            options={{
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                wordWrap: 'on',
                                lineNumbers: 'off',
                                folding: false,
                                lineDecorationsWidth: 0,
                                lineNumbersMinChars: 0,
                                glyphMargin: false,
                            }}
                        />
                        <p className="text-xs text-muted">
                            Groups for group-based feature flags in JSON format. Used when testing flags that target
                            organizations, teams, or other groups rather than individual users.
                        </p>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex gap-2">
                        <LemonButton
                            type="primary"
                            loading={isLoading}
                            onClick={handleSubmit}
                            disabledReason={
                                !selectedPerson || !formData.person_id?.trim() ? 'Please select a person' : undefined
                            }
                        >
                            Test evaluation
                        </LemonButton>
                        <LemonButton onClick={handleClear} disabled={isLoading}>
                            Clear
                        </LemonButton>
                    </div>

                    {/* Error Display */}
                    {error && (
                        <LemonBanner type="error">
                            <div>
                                <div className="font-medium">Test Evaluation Failed</div>
                                <div className="text-sm mt-1">{error}</div>
                                {error.toLowerCase().includes('build person properties') && (
                                    <div className="text-xs mt-2 text-muted">
                                        <strong>Solutions:</strong>
                                        <ul className="list-disc list-inside mt-1 space-y-1">
                                            <li>Try a more recent timestamp when this person was active</li>
                                            <li>Remove the timestamp to test with current person properties</li>
                                            <li>Select a different person who was active at that time</li>
                                        </ul>
                                    </div>
                                )}
                                {error.toLowerCase().includes('timestamp') &&
                                    !error.toLowerCase().includes('build person properties') && (
                                        <div className="text-xs mt-2 text-muted">
                                            <strong>Tip:</strong> When using historical timestamps, the person must have
                                            existed at that time and had the necessary properties for evaluation.
                                        </div>
                                    )}
                                {error.toLowerCase().includes('person') &&
                                    error.toLowerCase().includes('not found') && (
                                        <div className="text-xs mt-2 text-muted">
                                            <strong>Tip:</strong> Try selecting a different person or removing the
                                            timestamp to test with current data.
                                        </div>
                                    )}
                            </div>
                        </LemonBanner>
                    )}
                </div>

                {/* Right Panel - Analysis and Properties */}
                <div className={`flex-1 bg-bg-light p-6 rounded-lg border ${!result ? 'content-center' : ''}`}>
                    {result ? (
                        <div className="space-y-6">
                            {/* Evaluation Result */}
                            <div className="space-y-3">
                                <h5 className="font-semibold">Evaluation Result</h5>

                                <div className="space-y-2">
                                    <LemonLabel>Flag Result</LemonLabel>
                                    <div
                                        className={`px-3 py-2 rounded text-sm font-mono ${
                                            result.result === true ||
                                            (typeof result.result === 'string' && result.result !== 'false')
                                                ? 'bg-success-highlight text-success'
                                                : 'bg-danger-highlight text-danger'
                                        }`}
                                    >
                                        {typeof result.result === 'boolean'
                                            ? result.result
                                                ? 'true'
                                                : 'false'
                                            : result.result}
                                    </div>
                                </div>

                                {result.payload && (
                                    <div className="space-y-2">
                                        <LemonLabel>Payload</LemonLabel>
                                        <div className="px-3 py-2 rounded text-sm font-mono bg-bg-light">
                                            {JSON.stringify(result.payload, null, 2)}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Two Column Layout: Conditions and Properties */}
                            <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
                                {/* Left Column - Condition Analysis */}
                                {result.conditions && result.conditions.length > 0 && (
                                    <div className="space-y-3 xl:col-span-2">
                                        <LemonLabel>Condition Analysis</LemonLabel>

                                        <div className="space-y-3 max-h-96 overflow-auto">
                                            {result.conditions.map((condition) => (
                                                <div
                                                    key={condition.index}
                                                    className={`border rounded-lg p-3 ${
                                                        condition.matched
                                                            ? 'border-success bg-success-highlight'
                                                            : condition.rollout_excluded
                                                              ? 'border-warning bg-warning-highlight'
                                                              : 'border-muted bg-bg-light'
                                                    }`}
                                                >
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <h6 className="font-medium text-sm">
                                                            Condition #{condition.index}
                                                        </h6>
                                                        <span
                                                            className={`px-2 py-1 rounded text-xs font-mono ${
                                                                condition.matched
                                                                    ? 'bg-success text-success-content'
                                                                    : condition.rollout_excluded
                                                                      ? 'bg-warning text-warning-content'
                                                                      : 'bg-muted text-muted-alt'
                                                            }`}
                                                        >
                                                            {condition.matched
                                                                ? 'MATCHED'
                                                                : condition.rollout_excluded
                                                                  ? 'ROLLOUT EXCLUDED'
                                                                  : 'NOT MATCHED'}
                                                        </span>
                                                        {condition.rollout_percentage < 100 && (
                                                            <span className="px-2 py-1 rounded text-xs bg-bg-light text-muted font-mono">
                                                                {condition.rollout_percentage}%
                                                            </span>
                                                        )}
                                                    </div>

                                                    <div className="mb-2 text-xs text-muted">
                                                        {condition.explanation}
                                                    </div>

                                                    {condition.properties.length > 0 && (
                                                        <div className="space-y-1">
                                                            {condition.properties.map((property, idx) => (
                                                                <div
                                                                    key={`${property.key}-${idx}`}
                                                                    className="text-xs text-muted pl-2"
                                                                >
                                                                    • {property.explanation}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Right Column - Person Properties */}
                                <div className="space-y-3 xl:col-span-3">
                                    <div className="flex items-center justify-between">
                                        <LemonLabel>
                                            Person Properties {formData.timestamp ? 'at evaluation time' : '(current)'}
                                        </LemonLabel>
                                        {Object.keys(result.person_properties).length > 0 && (
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => setShowAllProperties(!showAllProperties)}
                                            >
                                                {showAllProperties ? 'Show used only' : 'Show all'}
                                            </LemonButton>
                                        )}
                                    </div>

                                    <div className="max-h-96 overflow-auto">
                                        {(() => {
                                            const usedProps = getUsedProperties()
                                            const propertiesToShow = showAllProperties
                                                ? Object.keys(result.person_properties)
                                                : Array.from(usedProps)

                                            const sortedProperties = propertiesToShow.sort((a, b) => {
                                                // Show used properties first, then alphabetical
                                                const aUsed = usedProps.has(a)
                                                const bUsed = usedProps.has(b)
                                                if (aUsed && !bUsed) {
                                                    return -1
                                                }
                                                if (!aUsed && bUsed) {
                                                    return 1
                                                }
                                                return a.localeCompare(b)
                                            })

                                            if (Object.keys(result.person_properties).length === 0) {
                                                return (
                                                    <div className="text-center py-4 text-muted">
                                                        <p>No person properties available</p>
                                                        <p className="text-xs mt-1">
                                                            This person has no properties, or they were not included in
                                                            the evaluation
                                                        </p>
                                                    </div>
                                                )
                                            }

                                            if (sortedProperties.length === 0) {
                                                return (
                                                    <div className="text-center py-4 text-muted">
                                                        <p>No properties used in conditions</p>
                                                        <p className="text-xs mt-1">
                                                            This person has{' '}
                                                            {Object.keys(result.person_properties).length} properties,
                                                            but none were used in flag conditions.{' '}
                                                            <button
                                                                className="text-primary cursor-pointer underline"
                                                                onClick={() => setShowAllProperties(true)}
                                                            >
                                                                Show all properties
                                                            </button>
                                                        </p>
                                                    </div>
                                                )
                                            }

                                            return (
                                                <LemonTable
                                                    columns={[
                                                        {
                                                            title: 'Property',
                                                            key: 'property',
                                                            render: (_, record: { key: string }) => (
                                                                <div className="flex items-center gap-2">
                                                                    <span className="font-medium">
                                                                        {formatPropertyKey(record.key)}
                                                                    </span>
                                                                    {usedProps.has(record.key) && (
                                                                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-success-highlight text-success border border-success">
                                                                            Used in condition
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            ),
                                                        },
                                                        {
                                                            title: 'Value',
                                                            key: 'value',
                                                            render: (_, record: { key: string }) => (
                                                                <span
                                                                    className={`px-2 py-1 rounded text-xs font-mono ${
                                                                        result.person_properties[record.key] === null ||
                                                                        result.person_properties[record.key] ===
                                                                            undefined
                                                                            ? 'bg-muted text-muted-alt'
                                                                            : 'bg-bg-light border'
                                                                    }`}
                                                                >
                                                                    {formatPropertyValue(
                                                                        result.person_properties[record.key]
                                                                    )}
                                                                </span>
                                                            ),
                                                        },
                                                    ]}
                                                    dataSource={sortedProperties.map((key) => ({ key }))}
                                                    rowKey={(record) => record.key}
                                                    size="small"
                                                />
                                            )
                                        })()}
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="flex-grow flex items-center justify-center h-64">
                            <div className="text-center text-muted">
                                <p className="text-lg font-medium mb-2">No evaluation analysis yet</p>
                                <p className="text-sm">
                                    Run a test evaluation to see condition analysis and person properties here
                                </p>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
