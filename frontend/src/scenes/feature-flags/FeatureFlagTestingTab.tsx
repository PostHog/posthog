import { useState } from 'react'

import {
    LemonButton,
    LemonInput,
    LemonBanner,
    LemonLabel,
    LemonSelect,
    LemonCalendarSelectInput,
    LemonTable,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import type { FeatureFlagType } from '~/types'

interface PropertyAnalysis {
    key: string
    operator: string
    value: any
    actual_value: any
    matched: boolean
    explanation: string
}

interface ConditionAnalysis {
    index: number
    matched: boolean
    rollout_excluded?: boolean
    result: string
    explanation: string
    rollout_percentage: number
    variant?: string
    properties: PropertyAnalysis[]
}

interface TestResult {
    flag_key: string
    result: boolean | string
    reason: string
    condition_index: number | null
    payload: any
    person_properties: Record<string, any>
    conditions?: ConditionAnalysis[]
}

interface TestFormData {
    distinct_id: string
    person_id: string
    timestamp: string
    groups: string
}

export function FeatureFlagTestingTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const [formData, setFormData] = useState<TestFormData>({
        distinct_id: '',
        person_id: '',
        timestamp: '',
        groups: '',
    })

    const [identifierType, setIdentifierType] = useState<'distinct_id' | 'person_id'>('distinct_id')
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [result, setResult] = useState<TestResult | null>(null)
    const [showAllProperties, setShowAllProperties] = useState(false)
    const [datePickerOpen, setDatePickerOpen] = useState(false)
    const [datePickerValue, setDatePickerValue] = useState<ReturnType<typeof dayjs> | undefined>(undefined)

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
        if (!formData.distinct_id.trim() && !formData.person_id.trim()) {
            setError('Please provide either a distinct_id or person_id')
            return
        }

        setIsLoading(true)
        setError(null)
        setResult(null)

        try {
            let groups: Record<string, string> = {}
            if (formData.groups.trim()) {
                try {
                    groups = JSON.parse(formData.groups)
                } catch {
                    throw new Error('Groups must be valid JSON (e.g., {"company": "acme"})')
                }
            }

            const data: any = { groups }

            if (identifierType === 'distinct_id' && formData.distinct_id.trim()) {
                data.distinct_id = formData.distinct_id.trim()
            }
            if (identifierType === 'person_id' && formData.person_id.trim()) {
                data.person_id = formData.person_id.trim()
            }
            if (formData.timestamp.trim()) {
                data.timestamp = formData.timestamp.trim()
            }

            const response = await api.featureFlags.testEvaluation(featureFlag.id, data)
            setResult(response)
        } catch (err) {
            if (err instanceof Error) {
                if (err.message.includes('Person not found')) {
                    setError(
                        'Person not found. Please check that the distinct_id or person_id exists in your PostHog instance.'
                    )
                } else {
                    setError(err.message)
                }
            } else {
                setError('Failed to evaluate flag')
            }
        } finally {
            setIsLoading(false)
        }
    }

    const handleClear = (): void => {
        setFormData({
            distinct_id: '',
            person_id: '',
            timestamp: '',
            groups: '',
        })
        setDatePickerValue(undefined)
        setError(null)
        setResult(null)
        setShowAllProperties(false)
    }

    return (
        <div className="space-y-6">
            <div>
                <h3 className="font-semibold">Test flag evaluation</h3>
                <p className="text-muted">
                    Test how this feature flag evaluates for a specific user, optionally at a historical timestamp. This
                    uses Python evaluation and provides detailed explanations of why the flag matched or didn't match.
                </p>
            </div>

            <div className="flex gap-6">
                {/* Left Panel - Form */}
                <div className="flex-1 space-y-4 max-w-md bg-bg-light p-6 rounded-lg border">
                    <h4 className="font-semibold">Test Parameters</h4>

                    {/* User Identifier */}
                    <div className="space-y-3">
                        <LemonLabel>User Identifier</LemonLabel>
                        <LemonSelect
                            placeholder="Select identifier type"
                            value={identifierType}
                            onChange={(value) => setIdentifierType(value as 'distinct_id' | 'person_id')}
                            options={[
                                { value: 'distinct_id', label: 'Distinct ID' },
                                { value: 'person_id', label: 'Person ID' },
                            ]}
                        />

                        {identifierType === 'distinct_id' ? (
                            <div>
                                <LemonInput
                                    placeholder="Enter distinct_id (e.g., user@example.com)"
                                    value={formData.distinct_id}
                                    onChange={(value) => setFormData((prev) => ({ ...prev, distinct_id: value }))}
                                />
                                <p className="text-xs text-muted mt-1">
                                    Use a distinct_id that exists in your PostHog instance. You can find these in the
                                    Persons page.
                                </p>
                            </div>
                        ) : (
                            <div>
                                <LemonInput
                                    placeholder="Enter person_id (UUID format)"
                                    value={formData.person_id}
                                    onChange={(value) => setFormData((prev) => ({ ...prev, person_id: value }))}
                                />
                                <p className="text-xs text-muted mt-1">
                                    Use a person UUID that exists in your PostHog instance.
                                </p>
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
                            onChange={(selectedDate) => {
                                setDatePickerValue(selectedDate)
                                setFormData((prev) => ({
                                    ...prev,
                                    timestamp: selectedDate ? selectedDate.toISOString() : '',
                                }))
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
                            onChange={(value) => setFormData((prev) => ({ ...prev, groups: value || '' }))}
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
                            placeholder='{"company": "acme", "team": "engineering"}'
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
                                !formData.distinct_id.trim() && !formData.person_id.trim()
                                    ? 'Please provide a distinct_id or person_id'
                                    : undefined
                            }
                        >
                            Test evaluation
                        </LemonButton>
                        <LemonButton onClick={handleClear} disabled={isLoading}>
                            Clear
                        </LemonButton>
                    </div>

                    {/* Error Display */}
                    {error && <LemonBanner type="error">{error}</LemonBanner>}
                </div>

                {/* Right Panel - Analysis and Properties */}
                <div className="flex-1 bg-bg-light p-6 rounded-lg border">
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
                                {Object.keys(result.person_properties).length > 0 && (
                                    <div className="space-y-3 xl:col-span-3">
                                        <div className="flex items-center justify-between">
                                            <LemonLabel>
                                                Person Properties{' '}
                                                {formData.timestamp ? 'at evaluation time' : '(current)'}
                                            </LemonLabel>
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => setShowAllProperties(!showAllProperties)}
                                            >
                                                {showAllProperties ? 'Show used only' : 'Show all'}
                                            </LemonButton>
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

                                                if (sortedProperties.length === 0) {
                                                    return (
                                                        <div className="text-center py-4 text-muted">
                                                            No properties used in conditions
                                                        </div>
                                                    )
                                                }

                                                return (
                                                    <LemonTable
                                                        columns={[
                                                            {
                                                                title: 'Property',
                                                                key: 'property',
                                                                render: (_, key: string) => (
                                                                    <div className="flex items-center gap-2">
                                                                        <span className="font-medium">
                                                                            {formatPropertyKey(key)}
                                                                        </span>
                                                                        {usedProps.has(key) && (
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
                                                                render: (_, key: string) => (
                                                                    <span
                                                                        className={`px-2 py-1 rounded text-xs font-mono ${
                                                                            result.person_properties[key] === null ||
                                                                            result.person_properties[key] === undefined
                                                                                ? 'bg-muted text-muted-alt'
                                                                                : 'bg-bg-light border'
                                                                        }`}
                                                                    >
                                                                        {formatPropertyValue(
                                                                            result.person_properties[key]
                                                                        )}
                                                                    </span>
                                                                ),
                                                            },
                                                        ]}
                                                        dataSource={sortedProperties}
                                                        rowKey={(key) => key}
                                                        size="small"
                                                        pagination={false}
                                                    />
                                                )
                                            })()}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="flex items-center justify-center h-64 rounded border-2 border-dashed border-border">
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
