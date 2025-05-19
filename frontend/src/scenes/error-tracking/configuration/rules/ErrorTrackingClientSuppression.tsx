import { LemonCard, LemonDivider } from '@posthog/lemon-ui'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import ErrorTrackingRules from './ErrorTrackingRules'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from './types'

export function ErrorTrackingClientSuppression(): JSX.Element {
    return (
        <ErrorTrackingRules<ErrorTrackingSuppressionRule> ruleType={ErrorTrackingRuleType.Suppression}>
            {({ rule, editable }) => {
                return (
                    <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                        <div className="flex gap-2 justify-between px-2 py-3">
                            <div className="flex gap-1 items-center">
                                <div>Ignore exceptions that match </div>
                                <ErrorTrackingRules.Operator rule={rule} editable={editable} />
                                <div>of the following filters:</div>
                            </div>
                            <ErrorTrackingRules.Actions rule={rule} editable={editable} />
                        </div>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <ErrorTrackingRules.Filters
                                rule={rule}
                                editable={editable}
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                propertyAllowList={{
                                    [TaxonomicFilterGroupType.EventProperties]: [
                                        '$exception_types',
                                        '$exception_values',
                                    ],
                                }}
                            />
                        </div>
                    </LemonCard>
                )
            }}
        </ErrorTrackingRules>
    )
}
