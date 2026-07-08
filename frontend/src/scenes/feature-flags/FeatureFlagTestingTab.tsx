import { useActions, useValues } from 'kea'

import { LemonButton, LemonBanner, LemonLabel, LemonCalendarSelectInput, LemonSelect } from '@posthog/lemon-ui'

import { PropertiesTable } from 'lib/components/PropertiesTable/PropertiesTable'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import type { Dayjs } from 'lib/dayjs'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import type { FeatureFlagType, PersonType } from '~/types'
import { PropertyDefinitionType } from '~/types'

import type { ConditionAnalysis } from './featureFlagTestingLogic'
import { featureFlagTestingLogic } from './featureFlagTestingLogic'

// Matches SUPER_CONDITION_INDEX in rust/feature-flags/src/api/types.rs: the early-access
// enrollment super condition has no position among the zero-based release conditions.
const SUPER_CONDITION_INDEX = -1

const CONDITION_DISPLAY_STYLES = {
    success: {
        card: 'border-success bg-success-highlight',
        badge: 'bg-success text-success-content',
    },
    info: {
        card: 'border-info bg-info-highlight',
        badge: 'bg-info text-info-content',
    },
    warning: {
        card: 'border-warning bg-warning-highlight',
        badge: 'bg-warning text-warning-content',
    },
    muted: {
        card: 'border-muted bg-bg-light',
        badge: 'bg-muted text-muted-alt',
    },
} as const

export function FeatureFlagTestingTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const logic = featureFlagTestingLogic({ flagId: featureFlag.id! })

    const {
        testFormData: formData,
        includeTime,
        testResult: result,
        datePickerOpen,
        datePickerValue,
        testEvaluationLoading: isLoading,
        selectedPerson,
        usedProperties,
        enrichedConditions,
        hasValidPerson,
        errorDisplay,
        personDistinctIds,
        hasMultipleDistinctIds,
        bucketingDistinctId,
    } = useValues(logic)

    const {
        setTestFormData,
        setDatePickerOpen,
        setDatePickerValue,
        setSelectedPerson,
        setIncludeTime,
        clearTestForm,
        testFlagEvaluation,
    } = useActions(logic)

    const handleSubmit = (): void => {
        testFlagEvaluation({ flagId: featureFlag.id!, formData })
    }

    const hasConditions = !!result?.conditions?.length

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
                    <h4 className="font-semibold">Test parameters</h4>

                    {/* User Selection */}
                    <div className="space-y-3">
                        <LemonLabel>Select person</LemonLabel>
                        {/* Wrapper keeps the control on its own line — both LemonLabel and the
                            TaxonomicPopover render as inline-flex, so without a block wrapper a
                            narrow selected value would sit beside the label instead of below it. */}
                        <div>
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.Persons}
                                value={formData.distinct_id || ''}
                                onChange={(value, _, person) => {
                                    // `value` is the person's distinct_id for every Persons-tab
                                    // source, including the recent tab — which only carries a
                                    // name + distinct_id, not the full person (no uuid/distinct_ids).
                                    const distinctId = typeof value === 'string' ? value : ''
                                    if (distinctId) {
                                        setSelectedPerson((person as Partial<PersonType>) ?? null, distinctId)
                                        setTestFormData({ distinct_id: distinctId })
                                    } else {
                                        setSelectedPerson(null)
                                        setTestFormData({ distinct_id: '' })
                                    }
                                }}
                                groupTypes={[TaxonomicFilterGroupType.Persons]}
                                placeholder="Search for a person by name, email, or ID..."
                                allowClear
                                fullWidth
                                truncate
                                renderValue={() => {
                                    if (formData.distinct_id) {
                                        return <span>{selectedPerson?.name || formData.distinct_id}</span>
                                    }
                                    return null
                                }}
                            />
                        </div>
                        <p className="text-xs text-muted">
                            Search and select a person from your PostHog instance. You can search by name, email, or
                            distinct ID.
                        </p>

                        {formData.distinct_id &&
                            (hasMultipleDistinctIds ? (
                                <div className="space-y-2">
                                    <LemonLabel>Distinct ID for bucketing</LemonLabel>
                                    <LemonSelect
                                        fullWidth
                                        aria-label="Distinct ID for bucketing"
                                        truncateText={{ maxWidthClass: 'max-w-full' }}
                                        value={formData.distinct_id}
                                        onChange={(distinctId) => {
                                            if (distinctId) {
                                                setTestFormData({ distinct_id: distinctId })
                                            }
                                        }}
                                        options={personDistinctIds.map((id) => ({
                                            value: id,
                                            label: id,
                                            tooltip: id,
                                        }))}
                                    />
                                    <LemonBanner type="warning">
                                        <div className="text-sm">
                                            This person has {personDistinctIds.length} merged distinct IDs. Rollout and
                                            variant assignment are computed by hashing the distinct ID, so the result
                                            can differ depending on which one you pick. At runtime PostHog buckets using
                                            the distinct ID from the incoming request, which may not be the one selected
                                            here.
                                        </div>
                                    </LemonBanner>
                                </div>
                            ) : (
                                <div className="text-xs text-muted space-y-1 p-2 bg-bg-3000 rounded">
                                    <div>
                                        <strong>Distinct ID:</strong> {formData.distinct_id}
                                    </div>
                                </div>
                            ))}
                    </div>

                    {/* Optional Timestamp */}
                    <div className="space-y-3">
                        <LemonLabel>Historical timestamp (optional)</LemonLabel>
                        <LemonCalendarSelectInput
                            value={datePickerValue}
                            format={includeTime ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD'}
                            visible={datePickerOpen}
                            showTimeToggle
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
                            granularity={includeTime ? 'minute' : 'day'}
                            onToggleTime={(includeTimeValue) => {
                                setIncludeTime(includeTimeValue)
                            }}
                            clearable={true}
                            buttonProps={{
                                fullWidth: true,
                                onClick: () => setDatePickerOpen(true),
                                children: datePickerValue
                                    ? datePickerValue.format('YYYY-MM-DD HH:mm:ss')
                                    : 'Select date and time',
                            }}
                            placeholder="Select date and time"
                        />
                        <p className="text-xs text-muted">
                            If provided, evaluates the flag using person properties and flag conditions as they existed
                            at this time.
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
                            disabledReason={!hasValidPerson ? 'Please select a person' : undefined}
                        >
                            Test evaluation
                        </LemonButton>
                        <LemonButton onClick={clearTestForm} disabled={isLoading}>
                            Clear
                        </LemonButton>
                    </div>

                    {/* Error Display */}
                    {errorDisplay && (
                        <LemonBanner type="error">
                            <div>
                                <div className="font-medium">Test evaluation failed</div>
                                <div className="text-sm mt-1">{errorDisplay.message}</div>
                                {errorDisplay.helpText && (
                                    <div className="text-xs mt-2 text-muted">
                                        <strong>Tip:</strong> {errorDisplay.helpText}
                                    </div>
                                )}
                            </div>
                        </LemonBanner>
                    )}
                </div>

                {/* Right Panel - Analysis and Properties */}
                <div
                    className={`flex-1 bg-bg-light p-6 rounded-lg border ${result ? 'flex flex-col' : 'content-center'}`}
                >
                    {result ? (
                        <div className="space-y-6 flex-1 flex flex-col min-h-0">
                            {/* Evaluation Result */}
                            <div className="space-y-3">
                                <h5 className="font-semibold">Evaluation result</h5>

                                <div className="space-y-2">
                                    <LemonLabel>Flag result</LemonLabel>
                                    <div
                                        className={`px-3 py-2 rounded text-sm font-mono ${
                                            result.result
                                                ? 'bg-success-highlight text-success'
                                                : 'bg-danger-highlight text-danger'
                                        }`}
                                    >
                                        {typeof result.result === 'boolean'
                                            ? result.result
                                                ? 'true'
                                                : 'false'
                                            : String(result.result)}
                                    </div>
                                </div>

                                {/* Distinct ID used for rollout/variant bucketing. Only shown when the
                                    backend echoes an explicit value — it returns null when a different ID
                                    was actually bucketed against, and falling back to the requested ID
                                    here would mislabel which ID drove the result. */}
                                {bucketingDistinctId && (
                                    <div className="space-y-2">
                                        <LemonLabel>Bucketed using distinct ID</LemonLabel>
                                        <div className="px-3 py-2 rounded text-sm font-mono bg-bg-light break-all">
                                            {bucketingDistinctId}
                                        </div>
                                    </div>
                                )}

                                {/* Timestamp Warning */}
                                {formData.timestamp && (
                                    <LemonBanner type="info" className="mb-4">
                                        <strong>Historical evaluation:</strong> Both flag conditions and person
                                        properties reflect their state at the specified timestamp, not current values.
                                    </LemonBanner>
                                )}

                                {result.payload != null && (
                                    <div className="space-y-2">
                                        <LemonLabel>Payload</LemonLabel>
                                        <div className="px-3 py-2 rounded text-sm font-mono bg-bg-light">
                                            {JSON.stringify(result.payload, null, 2)}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Two Column Layout: Conditions and Properties */}
                            <div className="grid grid-cols-1 xl:grid-cols-5 gap-6 flex-1 min-h-0">
                                {/* Left Column - Condition Analysis */}
                                {hasConditions && (
                                    <div className="space-y-3 xl:col-span-2 flex flex-col min-h-0">
                                        <LemonLabel>Condition analysis</LemonLabel>

                                        <div className="flex-1 space-y-3 overflow-auto">
                                            {enrichedConditions.map((condition) => {
                                                const styles = CONDITION_DISPLAY_STYLES[condition.display.tone]

                                                return (
                                                    <div
                                                        key={condition.index}
                                                        className={`border rounded-lg p-3 break-words ${styles.card}`}
                                                    >
                                                        <div className="flex items-center gap-2 mb-2">
                                                            <h6 className="font-medium text-sm">
                                                                {condition.index === SUPER_CONDITION_INDEX
                                                                    ? 'Early access enrollment'
                                                                    : `Condition #${condition.index + 1}`}
                                                            </h6>
                                                            {condition.display.label && (
                                                                <span
                                                                    className={`px-2 py-1 rounded text-xs font-mono ${styles.badge}`}
                                                                >
                                                                    {condition.display.label}
                                                                </span>
                                                            )}
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
                                                                {condition.properties.map(
                                                                    (
                                                                        property: ConditionAnalysis['properties'][number],
                                                                        idx: number
                                                                    ) => (
                                                                        <div
                                                                            key={`${property.key}-${idx}`}
                                                                            className="text-xs text-muted pl-2"
                                                                        >
                                                                            • {property.explanation}
                                                                        </div>
                                                                    )
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    </div>
                                )}

                                {/* Right Column - Person Properties */}
                                <div
                                    className={`space-y-3 ${
                                        hasConditions ? 'xl:col-span-3' : 'xl:col-span-5'
                                    } flex flex-col min-h-0`}
                                >
                                    <div>
                                        <LemonLabel>
                                            Person properties {formData.timestamp ? 'at evaluation time' : '(current)'}
                                        </LemonLabel>
                                    </div>

                                    <div className="flex-1 overflow-auto">
                                        <PropertiesTable
                                            properties={result.person_properties}
                                            type={PropertyDefinitionType.Person}
                                            searchable={true}
                                            sortProperties={true}
                                            highlightedKeys={Array.from(usedProperties)}
                                            highlightVariant="subtle"
                                            embedded={true}
                                        />
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
