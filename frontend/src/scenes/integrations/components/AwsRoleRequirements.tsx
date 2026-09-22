import { useValues } from 'kea'

import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

// PostHog's own role, which a customer's trust policy has to name. Mirrors
// BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN per region, the role every AWS role integration assumes from.
const POSTHOG_ROLE_ARN_BY_REGION: Partial<Record<Region, string>> = {
    [Region.US]: 'arn:aws:iam::309986977637:role/posthog-external-batch-exports',
    [Region.EU]: 'arn:aws:iam::623789312881:role/posthog-external-batch-exports',
}

/**
 * The trust-policy checklist shown on the "assume IAM role" tab of an AWS integration setup modal.
 * The first two steps are the same for every AWS service, so callers only supply the permissions
 * their service needs.
 */
export function AwsRoleRequirements({ permissions }: { permissions: JSX.Element }): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)

    const posthogRoleArn = preflight?.region ? POSTHOG_ROLE_ARN_BY_REGION[preflight.region] : undefined

    const steps: JSX.Element[] = [
        posthogRoleArn ? (
            <>
                Create an IAM role with a trust policy that allows PostHog's role <code>{posthogRoleArn}</code> to
                assume it.
            </>
        ) : (
            <>
                Create an IAM role with a trust policy that allows PostHog's role to assume it. Check with your instance
                administrator to obtain the role to trust.
            </>
        ),
        <>
            The trust policy must require an <code>sts:ExternalId</code> condition equal to{' '}
            <code>posthog-{currentOrganization?.id}</code>. PostHog verifies this condition is enforced and exports will
            fail without it.
        </>,
        permissions,
    ]

    return (
        <div className="border border-border rounded p-4 bg-bg-light flex flex-col gap-3 text-sm">
            <p className="font-semibold m-0">Requirements</p>
            {steps.map((step, index) => (
                <div key={index} className="flex gap-3 items-start">
                    <span className="bg-primary-highlight text-primary-alt rounded-full w-5 h-5 flex items-center justify-center text-xs font-semibold shrink-0 mt-0.5">
                        {index + 1}
                    </span>
                    <p className="m-0 text-secondary">{step}</p>
                </div>
            ))}
        </div>
    )
}
