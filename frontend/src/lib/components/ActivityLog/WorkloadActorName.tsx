import { Link } from 'lib/lemon-ui/Link'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { WorkloadAttribution, workloadActorLabel } from './parseWorkloadAttribution'

/** The workload that made a change, in place of the organization owner its token acts as. */
export function WorkloadActorName({
    attribution,
    teamId,
}: {
    attribution: WorkloadAttribution
    /** The entry's project, which can differ from the current one in the organization audit log. */
    teamId?: number | null
}): JSX.Element {
    const label = workloadActorLabel(attribution)
    return (
        <span className="ph-no-capture">
            {attribution.runUrl ? (
                <Link to={attribution.runUrl} target="_blank" className="font-semibold">
                    {label}
                </Link>
            ) : (
                <strong>{label}</strong>
            )}
            {attribution.policyName ? (
                <>
                    <span>, through trust policy </span>
                    <Link
                        to={addProjectIdIfMissing(urls.settings('environment-trusted-workloads'), teamId ?? undefined)}
                    >
                        <em>{attribution.policyName}</em>
                    </Link>
                </>
            ) : null}
        </span>
    )
}
