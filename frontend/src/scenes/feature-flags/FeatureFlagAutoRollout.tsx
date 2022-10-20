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
    const { featureFlagRollbackInsight } = useValues(featureFlagLogic)
    const { createFeatureFlagRollbackInsight, setFilters } = useActions(featureFlagLogic)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: featureFlagRollbackInsight?.short_id,
        })
    )

    const { filters: trendsFilters } = useValues(trendsLogic(insightProps))

    const [hasCondition, setHasCondition] = useState(false)

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
                <div className="RollbackCondition mb-4 mt-2">
                    <Field name="auto_rollback">
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                id="flag-autorollback-checkbox"
                                label="Automatically disable the flag if rollback triggered"
                                onChange={() => onChange(!value)}
                                fullWidth
                                checked={value}
                            />
                        )}
                    </Field>
                    <Group name="rollback_conditions">
                        <div className="flex gap-2 items-center mt-4">
                            When
                            <Field name="threshold_metric">
                                <ActionFilter
                                    filters={trendsFilters}
                                    setFilters={(payload) => {
                                        setFilters(payload)
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
                            </Field>
                            is
                            <Field name="operator">
                                <LemonSelect
                                    options={[
                                        { label: 'greater than', value: 'gt' },
                                        { label: 'less than', value: 'lt' },
                                    ]}
                                />
                            </Field>
                            <Field name="threshold">
                                <LemonInput
                                    min={0}
                                    onChange={function Ke() {}}
                                    onPressEnter={function Ke() {}}
                                    type="number"
                                />
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
