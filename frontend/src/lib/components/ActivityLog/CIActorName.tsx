import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CIAttribution, ciActorLabel } from './parseCIAttribution'

/** The CI job that made a change, in place of the organization owner its token acts as. */
export function CIActorName({ attribution }: { attribution: CIAttribution }): JSX.Element {
    const label = ciActorLabel(attribution)
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
                    <Link to={urls.settings('environment-ci-trust-policies')}>
                        <em>{attribution.policyName}</em>
                    </Link>
                </>
            ) : null}
        </span>
    )
}
