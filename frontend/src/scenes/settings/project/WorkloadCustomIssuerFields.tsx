import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

export function WorkloadCustomIssuerFields(): JSX.Element {
    const { editingPolicy, issuerCheck, issuerCheckLoading, issuerCheckError, checkedIssuer, providers } =
        useValues(workloadTrustPoliciesLogic)
    const { checkIssuer } = useActions(workloadTrustPoliciesLogic)

    const current = editingPolicy.issuer.trim()
    const checked = issuerCheck && issuerCheck.issuer === current ? issuerCheck : null
    const checkError = issuerCheckError && checkedIssuer === current ? issuerCheckError : null
    const audience = checked?.audience ?? providers?.job_settings.host

    return (
        <div className="deprecated-space-y-4">
            <LemonField
                name="issuer"
                label="Issuer URL"
                help="Exactly as the issuer's tokens carry it in their iss claim. PostHog reads the issuer's OpenID configuration from it."
            >
                {({ value, onChange }) => (
                    <div className="flex gap-2 w-full">
                        <LemonInput
                            value={value}
                            onChange={onChange}
                            onPressEnter={value.trim() && !issuerCheckLoading ? checkIssuer : undefined}
                            placeholder="https://auth.example.com"
                            className="flex-1"
                            data-attr="workload-trust-policy-custom-issuer"
                        />
                        <LemonButton
                            type="secondary"
                            onClick={checkIssuer}
                            loading={issuerCheckLoading}
                            disabledReason={!value.trim() ? 'Enter the issuer URL first' : undefined}
                            data-attr="workload-trust-policy-check-issuer"
                        >
                            Check issuer
                        </LemonButton>
                    </div>
                )}
            </LemonField>
            {checked ? (
                <LemonBanner type="success">
                    PostHog found the issuer. It checks tokens with the keys at {checked.jwks_uri}
                    {checked.signing_algorithms.length ? `, signed with ${checked.signing_algorithms.join(', ')}` : ''}.
                </LemonBanner>
            ) : checkError ? (
                <LemonBanner type="error">{checkError}</LemonBanner>
            ) : null}
            <LemonBanner type="info">
                Jobs send a token from this issuer with the audience <code>{audience}</code>, and hog reads it from
                HOG_ID_TOKEN.{' '}
                {providers ? (
                    <Link to={providers.custom.docs_url} target="_blank">
                        Read the setup guide
                    </Link>
                ) : null}
            </LemonBanner>
            <div className="flex flex-wrap gap-4">
                <LemonField
                    name="subject_claim"
                    label="Subject claim"
                    help="The claim that names the workload, such as sub."
                    className="flex-1 min-w-60"
                >
                    <LemonInput placeholder="sub" data-attr="workload-trust-policy-subject-claim" />
                </LemonField>
                <LemonField
                    name="subject"
                    label="Subject value"
                    help="The exact value the subject claim must have."
                    className="flex-1 min-w-60"
                >
                    <LemonInput placeholder="repo:acme/web" data-attr="workload-trust-policy-subject" />
                </LemonField>
            </div>
            <div className="flex flex-wrap gap-4">
                <LemonField
                    name="subject_name_claim"
                    label="Name claim (optional)"
                    help="A claim with the workload's name, which must equal the workload name. Leave it empty to use the workload name only as a label."
                    className="flex-1 min-w-60"
                >
                    <LemonInput placeholder="name" data-attr="workload-trust-policy-subject-name-claim" />
                </LemonField>
                <LemonField name="subject_name" label="Workload name" className="flex-1 min-w-60">
                    <LemonInput placeholder="Deploy bot" data-attr="workload-trust-policy-subject-name" />
                </LemonField>
            </div>
            <LemonBanner type="warning">
                You choose the claims PostHog checks. Use claims the issuer sets itself, which a workload can't change.
                Otherwise another workload could get this policy's token.
            </LemonBanner>
        </div>
    )
}
