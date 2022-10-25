import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Group } from 'kea-forms'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Field } from 'lib/forms/Field'
import { useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { featureFlagLogic } from './featureFlagLogic'

export function FeatureFlagAutoRollback(): JSX.Element {
    const { featureFlagRollbackInsight, featureFlag } = useValues(featureFlagLogic)
    const { createFeatureFlagRollbackInsight, setFilters } = useActions(featureFlagLogic)
    console.log(featureFlagRollbackInsight)
    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: featureFlagRollbackInsight?.short_id,
        })
    )

    const { filters: trendsFilters } = useValues(trendsLogic(insightProps))

    const [hasCondition, setHasCondition] = useState(featureFlag.auto_rollback)

    return (
        <div>
            <div className="mb-2">
                <b>Auto rollback</b>
                <LemonTag type="warning" className="uppercase ml-2">
                    Beta
                </LemonTag>
                <div className="mt-2">
                    Specify the conditions in which this feature flag will trigger a warning or automatically roll back.
                </div>
            </div>
            {hasCondition && (
                <>
                    <div className="RollbackCondition mb-4 mt-2">
                        <Field name="auto_rollback">
                            {({ value, onChange }) => (
                                <div className="border rounded p-3" style={{ width: 'fit-content' }}>
                                    <LemonCheckbox
                                        id="flag-autorollback-checkbox"
                                        label="Automatically disable the flag if rollback triggered"
                                        onChange={() => onChange(!value)}
                                        checked={value}
                                    />
                                </div>
                            )}
                        </Field>
                        <div className="mt-3">
                            <b>Metrics based rollback</b>
                        </div>
                        <Group name={['rollback_conditions', 0]}>
                            <div className="flex gap-2 items-center mt-4">
                                When
                                <Field name="threshold_metric">
                                    {({ onChange }) => (
                                        <ActionFilter
                                            filters={trendsFilters}
                                            setFilters={(payload) => {
                                                setFilters(payload)
                                                onChange({
                                                    ...trendsFilters,
                                                    ...payload,
                                                })
                                            }}
                                            typeKey={'feature-flag-rollback-trends'}
                                            buttonCopy={'Add graph series'}
                                            showSeriesIndicator
                                            showNestedArrow
                                            entitiesLimit={1}
                                            propertiesTaxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.EventProperties,
                                                TaxonomicFilterGroupType.PersonProperties,
                                                TaxonomicFilterGroupType.EventFeatureFlags,
                                                TaxonomicFilterGroupType.Cohorts,
                                                TaxonomicFilterGroupType.Elements,
                                            ]}
                                        />
                                    )}
                                </Field>
                                is
                                <Field name="operator">
                                    {({ value, onChange }) => (
                                        <LemonSelect
                                            value={value}
                                            onChange={onChange}
                                            options={[
                                                { label: 'greater than', value: 'gt' },
                                                { label: 'less than', value: 'lt' },
                                            ]}
                                        />
                                    )}
                                </Field>
                                <Field name="threshold">
                                    <LemonInput min={0} type="number" />
                                </Field>
                            </div>
                        </Group>

                        <div className="mt-4">
                            <BindLogic logic={insightLogic} props={insightProps}>
                                <InsightContainer
                                    disableHeader={false}
                                    disableTable={true}
                                    disableCorrelationTable={true}
                                />
                            </BindLogic>
                        </div>
                    </div>
                    <div>
                        <div className="mb-2">
                            <b>Sentry errors based rollback</b>
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonCheckbox
                                id="errors-autorollback-checkbox"
                                onChange={() => {}}
                                // checked={ }
                            />
                            <Group name={['rollback_conditions', 1]}>
                                {/* <Field name="enabled"> */}
                                {/* {({ value, onChange }) => ( */}
                                {/* )} */}
                                {/* </Field> */}
                                Trigger when there is a
                                <Field name="threshold">
                                    {({ value, onChange }) => (
                                        <LemonInput
                                            value={value || 30}
                                            suffix={<>%</>}
                                            type="number"
                                            min={0}
                                            onChange={onChange}
                                        />
                                    )}
                                </Field>
                                <Field name="operator">
                                    {({ value, onChange }) => (
                                        <LemonSelect
                                            options={[
                                                { label: 'increase', value: 'gt' },
                                                { label: 'decrease', value: 'lt' },
                                            ]}
                                            value={value}
                                            onChange={onChange}
                                        />
                                    )}
                                </Field>
                            </Group>
                            in errors
                        </div>
                    </div>
                </>
            )}
            {!hasCondition && (
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        setHasCondition(true)
                        createFeatureFlagRollbackInsight()
                    }}
                >
                    Add condition
                </LemonButton>
            )}
        </div>
    )
}
