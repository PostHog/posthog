import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { capitalizeFirstLetter, genericOperatorMap, humanFriendlyNumber } from 'lib/utils'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { RolloutConditionType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'

interface FeatureFlagAutoRollbackProps {
    readOnly?: boolean
}

export function FeatureFlagAutoRollback({ readOnly }: FeatureFlagAutoRollbackProps): JSX.Element | null {
    const { featureFlag, sentryIntegrationEnabled, sentryErrorCount, insightRollingAverages } =
        useValues(featureFlagLogic)
    const { addRollbackCondition, removeRollbackCondition, loadInsightAtIndex } = useActions(featureFlagLogic)
    const { user } = useValues(userLogic)

    if (!featureFlag.rollback_conditions || featureFlag.rollback_conditions.length === 0) {
        return null
    }

    return (
        <>
            <SceneSection
                title={
                    <span className="flex items-center gap-2">
                        Auto rollback
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </span>
                }
                description={
                    !readOnly && 'Specify the conditions in which this feature flag will automatically roll back.'
                }
            >
                {readOnly &&
                    featureFlag.rollback_conditions &&
                    featureFlag.rollback_conditions.map((rollback_condition, index) => (
                        <>
                            {index > 0 && <div className="condition-set-separator">OR</div>}
                            {rollback_condition.threshold_type === 'insight' &&
                            rollback_condition.threshold_metric?.events?.[0]?.name ? (
                                <div className="mb-4 border rounded p-4 bg-surface-primary">
                                    <b>{`${capitalizeFirstLetter(rollback_condition.threshold_type)} based rollback`}</b>
                                    <LemonDivider className="my-3" />
                                    <div className="flex items-center">
                                        {insightRollingAverages[index] && (
                                            <>
                                                <b>{rollback_condition.threshold_metric.events[0].name}</b>
                                                &nbsp; trailing average is {insightRollingAverages[index]}.
                                            </>
                                        )}
                                        &nbsp;Trigger when trailing average of &nbsp;
                                        <b>{rollback_condition.threshold_metric.events[0].name}</b>
                                        &nbsp; is&nbsp;
                                        {rollback_condition.operator &&
                                            genericOperatorMap[rollback_condition.operator]}{' '}
                                        {rollback_condition.threshold}
                                    </div>
                                </div>
                            ) : (
                                <div className="mb-4 border rounded p-4 bg-surface-primary">
                                    <b>{`${capitalizeFirstLetter(rollback_condition.threshold_type)} based rollback`}</b>
                                    <LemonDivider className="my-3" />
                                    <div className="flex items-center">
                                        Trigger when there is a&nbsp;<b>{rollback_condition.threshold}%</b>
                                        &nbsp;increase in errors
                                    </div>
                                </div>
                            )}
                        </>
                    ))}
                {!readOnly &&
                    featureFlag.rollback_conditions &&
                    featureFlag.rollback_conditions.map((_, index) => (
                        <>
                            {index > 0 && <div className="condition-set-separator">OR</div>}
                            <div className="mb-4 border rounded p-4 bg-surface-primary">
                                <Group name={['rollback_conditions', index]}>
                                    <div className="flex items-center justify-between">
                                        <div className="flex">
                                            <div className="mt-3 mr-3">
                                                <b>Rollback Condition Type</b>
                                            </div>
                                            <LemonField name="threshold_type">
                                                {({ value, onChange }) => (
                                                    <LemonSelect
                                                        value={value}
                                                        onChange={onChange}
                                                        options={[
                                                            {
                                                                value: RolloutConditionType.Sentry,
                                                                label: 'Error Based',
                                                            },
                                                            {
                                                                value: RolloutConditionType.Insight,
                                                                label: 'Metric Based',
                                                            },
                                                        ]}
                                                    />
                                                )}
                                            </LemonField>
                                        </div>
                                        <LemonButton
                                            icon={<IconTrash />}
                                            noPadding
                                            onClick={() => {
                                                removeRollbackCondition(index)
                                            }}
                                        />
                                    </div>
                                    <LemonDivider className="my-3" />
                                    {featureFlag.rollback_conditions[index].threshold_type == 'insight' ? (
                                        <div className="flex gap-2 items-center mt-4">
                                            <LemonField name="threshold_metric">
                                                {({ value, onChange }) => (
                                                    <ActionFilter
                                                        filters={value}
                                                        setFilters={(payload) => {
                                                            onChange({
                                                                ...payload,
                                                            })
                                                            loadInsightAtIndex(index, payload)
                                                        }}
                                                        typeKey={'feature-flag-rollback-trends-' + index}
                                                        buttonCopy="Add graph series"
                                                        showSeriesIndicator={false}
                                                        showNestedArrow
                                                        hideRename={true}
                                                        entitiesLimit={1}
                                                        mathAvailability={MathAvailability.None}
                                                        propertiesTaxonomicGroupTypes={[
                                                            TaxonomicFilterGroupType.EventProperties,
                                                            TaxonomicFilterGroupType.PersonProperties,
                                                            TaxonomicFilterGroupType.EventFeatureFlags,
                                                            TaxonomicFilterGroupType.Cohorts,
                                                            TaxonomicFilterGroupType.Elements,
                                                        ]}
                                                    />
                                                )}
                                            </LemonField>
                                            <span>
                                                trailing 7 day average is&nbsp;
                                                {insightRollingAverages[index] !== undefined ? (
                                                    <b>{insightRollingAverages[index]}</b>
                                                ) : (
                                                    <Spinner />
                                                )}
                                                . Trigger when trailing average is
                                            </span>
                                            <LemonField name="operator">
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
                                            </LemonField>
                                            <LemonField name="threshold">
                                                <LemonInput min={0} type="number" />
                                            </LemonField>
                                        </div>
                                    ) : sentryIntegrationEnabled ? (
                                        <div>
                                            <div className="flex items-center">
                                                {sentryErrorCount ? (
                                                    <span>
                                                        <b>{humanFriendlyNumber(sentryErrorCount)} </b> Sentry errors in
                                                        the past 24 hours.{' '}
                                                    </span>
                                                ) : (
                                                    <Spinner />
                                                )}
                                                <span>&nbsp;Trigger when there is a</span>
                                                <LemonField name="threshold" className="ml-3 mr-3">
                                                    {({ value, onChange }) => (
                                                        <LemonInput
                                                            value={value}
                                                            suffix={<>%</>}
                                                            type="number"
                                                            min={0}
                                                            onChange={onChange}
                                                        />
                                                    )}
                                                </LemonField>
                                                <LemonField name="operator" className="mr-3">
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
                                                </LemonField>
                                                <span>
                                                    to{' '}
                                                    {sentryErrorCount ? (
                                                        <b>
                                                            {humanFriendlyNumber(
                                                                Math.round(
                                                                    sentryErrorCount *
                                                                        (1 +
                                                                            (featureFlag.rollback_conditions[index]
                                                                                .threshold || 0) /
                                                                                100)
                                                                )
                                                            )}
                                                        </b>
                                                    ) : (
                                                        <Spinner />
                                                    )}{' '}
                                                    errors.
                                                </span>
                                                <div />
                                            </div>
                                        </div>
                                    ) : user?.is_staff ? (
                                        <div className="mt-4">
                                            <b>This feature requires an active Sentry integration.</b>
                                            <br />
                                            <Link to={urls.instanceSettings()}>Go to Instance Settings</Link> and update
                                            the <code>"SENTRY_"</code> properties from your Sentry account to enable.
                                        </div>
                                    ) : (
                                        <p className="text-secondary">
                                            This PostHog instance is not configured for Sentry. Please contact the
                                            instance owner to configure it.
                                        </p>
                                    )}
                                </Group>
                            </div>
                        </>
                    ))}
                {!readOnly && featureFlag.rollback_conditions && featureFlag.rollback_conditions.length > 0 && (
                    <LemonButton type="secondary" onClick={addRollbackCondition}>
                        Add condition
                    </LemonButton>
                )}
            </SceneSection>
        </>
    )
}
