import { LemonButton, LemonCard } from '@posthog/lemon-ui'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'
import { AssigneeSelect } from 'scenes/error-tracking/AssigneeSelect'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

export function ErrorTrackingAutoAssignment(): JSX.Element {
    const [rules, setRules] = useState<
        { assignee: ErrorTrackingIssueAssignee | null; properties: AnyPropertyFilter[] }[]
    >([])

    return (
        <div className="flex flex-col gap-y-2">
            {rules.map((rule, index) => (
                <LemonCard key={index} hoverEffect={false} className="flex flex-col p-3 gap-2p-3 gap-y-2">
                    <div className="flex gap-1 items-center">
                        <div>Assign to</div>
                        <AssigneeSelect
                            showName
                            type="secondary"
                            size="small"
                            unassignedLabel="Choose an assignee"
                            assignee={rule.assignee}
                            onChange={(assignee) => {
                                setRules([{ ...rule, assignee }])
                            }}
                        />
                    </div>
                    <PropertyFilters
                        propertyFilters={rule.properties ?? []}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.ErrorTrackingIssues]}
                        onChange={(properties: AnyPropertyFilter[]) => {
                            setRules([{ ...rule, properties }])
                        }}
                        pageKey={`error-tracking-auto-assignment-properties-${index}`}
                        buttonSize="small"
                        disablePopover
                    />
                </LemonCard>
            ))}

            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setRules([...rules, { assignee: null, properties: [] }])}
                >
                    Add rule
                </LemonButton>
            </div>
        </div>
    )
}
