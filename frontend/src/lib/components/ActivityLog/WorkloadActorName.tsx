import { Tooltip } from '@posthog/lemon-ui'

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
    const actor = attribution.runUrl ? (
        <Link to={attribution.runUrl} target="_blank" className="font-semibold">
            {label}
        </Link>
    ) : (
        <strong>{label}</strong>
    )
    return (
        <span className="ph-no-capture">
            {attribution.claims.length > 0 ? (
                <Tooltip
                    title={
                        <dl className="m-0">
                            {attribution.claims.map((claim) => (
                                <div key={claim.name} className="flex gap-1">
                                    <dt className="font-semibold">{claim.label}:</dt>
                                    <dd className="m-0 break-all">{claim.value}</dd>
                                </div>
                            ))}
                        </dl>
                    }
                >
                    <span>{actor}</span>
                </Tooltip>
            ) : (
                actor
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
