# Depot CI OIDC for cloud authentication

Depot CI supports OpenID Connect (OIDC) so workflows authenticate to cloud providers (AWS, GCP, Azure) with short-lived tokens instead of static credentials. This file mirrors `app/content/docs/ci/oidc.mdx`.

Contents:

- How it works and the token
- Configure a cloud provider (AWS example)
- The `sub` claim and wildcards
- Migrating from GitHub Actions OIDC
- Token claim reference

## How it works and the token

Depot CI automatically issues a signed JWT to each job. Set `permissions: id-token: write` in the workflow YAML for the token to be issued. The cloud provider verifies the token against Depot CI's public endpoint and grants access based on the claims inside it.

- **Issuer (`iss`)**: `https://identity.depot.dev`
- **JWKS endpoint**: `https://identity.depot.dev/keys`
- **Expiry (`exp`)**: 5 minutes from issuance
- **Subject (`sub`)**: `spiffe://identity.depot.dev/org/<orgID>/ci/github/<owner>/<repo>/ref/<ref>/sandbox/<sandboxID>`

## Configure a cloud provider

The general steps are the same for any OIDC-compatible provider:

1. Add `https://identity.depot.dev` as a trusted OIDC issuer.
2. Create a role or service account that grants access based on token claims.
3. Request the token in the workflow and use it to authenticate.

### AWS example

1. Add Depot CI as an identity provider in AWS IAM: provider URL `https://identity.depot.dev`, audience `sts.amazonaws.com`.
2. Create an IAM role with a trust policy scoped by the `sub` and `aud` claims:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": { "Federated": "arn:aws:iam::ACCOUNT:oidc-provider/identity.depot.dev" },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": { "identity.depot.dev:aud": "sts.amazonaws.com" },
           "StringLike": {
             "identity.depot.dev:sub": "spiffe://identity.depot.dev/org/<orgID>/ci/github/my-org/my-repo/*"
           }
         }
       }
     ]
   }
   ```

3. Use the role in a workflow. Depot injects the token-request credentials into the environment, so `aws-actions/configure-aws-credentials` works without extra configuration:

   ```yaml
   jobs:
     deploy:
       runs-on: depot-ubuntu-latest
       permissions:
         id-token: write
         contents: read
       steps:
         - uses: actions/checkout@v4
         - uses: aws-actions/configure-aws-credentials@v4
           with:
             role-to-assume: arn:aws:iam::123456789012:role/my-role
             aws-region: us-east-1
         - run: aws s3 ls
   ```

## The `sub` claim and wildcards

Scope trust policies by matching the `sub` claim. Full form:

```text
spiffe://identity.depot.dev/org/<orgID>/ci/github/<owner>/<repo>/ref/<ref>/sandbox/<sandboxID>
```

Wildcard matches:

- Everything in a GitHub org: `spiffe://identity.depot.dev/org/<orgID>/ci/github/<owner>/*`
- A specific repository: `spiffe://identity.depot.dev/org/<orgID>/ci/github/<owner>/<repo>/*`
- A specific branch: `spiffe://identity.depot.dev/org/<orgID>/ci/github/<owner>/<repo>/ref/<ref>/sandbox/*`

## Migrating from GitHub Actions OIDC

`permissions: id-token: write` is required just as in GitHub Actions. What changes on the cloud-provider side:

|                     | GitHub Actions                                                      | Depot CI                                                                                         |
| ------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Issuer (`iss`)      | `https://token.actions.githubusercontent.com`                       | `https://identity.depot.dev`                                                                     |
| Subject (`sub`)     | `repo:owner/repo:ref:refs/heads/main`                               | `spiffe://identity.depot.dev/org/<orgID>/ci/github/<owner>/<repo>/ref/<ref>/sandbox/<sandboxID>` |
| Repo/branch scoping | `sub` (encoded in the subject)                                      | `sub`, or `repository` + `ref` claims (separate conditions)                                      |
| JWKS endpoint       | `https://token.actions.githubusercontent.com/.well-known/jwks.json` | `https://identity.depot.dev/keys`                                                                |

Add `https://identity.depot.dev` as a new identity provider and create a new trust policy rather than modifying the existing GitHub Actions one, so both providers work in parallel during the transition.

## Token claim reference

Standard claims: `iss`, `sub`, `aud` (set by the workload request, for example `sts.amazonaws.com`), `exp`, `iat`.

GitHub Actions-compatible claims: `repository`, `repository_owner`, `repository_id`, `repository_owner_id`, `repository_visibility`, `ref`, `ref_type`, `sha`, `actor`, `actor_id`, `event_name`, `head_ref`, `base_ref`, `workflow`, `workflow_ref`, `workflow_sha`, `run_id`, `run_number`, `run_attempt`.

Depot-specific claims: `org_id` (Depot organization ID), `job_id` (Depot CI job ID).
