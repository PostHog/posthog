import { LemonCard, LemonDivider } from '@posthog/lemon-ui'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import ErrorTrackingRules from './ErrorTrackingRules'
import { ErrorTrackingGroupingRule, ErrorTrackingRuleType } from './types'

export function ErrorTrackingCustomGrouping(): JSX.Element {
    return (
        <>
            <p>Group exceptions into issues using properties of the event.</p>
            <ErrorTrackingRules<ErrorTrackingGroupingRule> ruleType={ErrorTrackingRuleType.Grouping}>
                {({ rule, editable }) => {
                    return (
                        <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                            <div className="flex gap-2 justify-between px-2 py-3">
                                <div className="flex gap-1 items-center">
                                    <div>Group exceptions as a single issue when</div>
                                    <ErrorTrackingRules.Operator rule={rule} editable={editable} />
                                    <div>filters match</div>
                                </div>
                                <ErrorTrackingRules.Actions rule={rule} editable={editable} />
                            </div>
                            <LemonDivider className="my-0" />
                            <div className="p-2">
                                <ErrorTrackingRules.Filters
                                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                    rule={rule}
                                    editable={editable}
                                />
                            </div>
                        </LemonCard>
                    )
                }}
            </ErrorTrackingRules>
        </>
    )
}
