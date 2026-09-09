# OpenID Connect single sign-on

OIDC is a platform feature. Billing grants it to the same plans as SAML. Self-hosted Enterprise licenses also include it.

## Configure an identity provider

1. Enable the existing `sso-settings-redesign` feature flag for the organization.
2. Verify the email domains that will use OIDC.
3. Open organization authentication settings. Select **Configure** under **OpenID Connect single sign-on**.
4. Create a confidential OIDC application in the identity provider. Enable the authorization code flow with PKCE and S256.
5. Copy the redirect URL from PostHog into the application.
6. Enter the issuer URL, client ID, and client secret in PostHog.
7. Select the verified domains for this configuration. Save the configuration.
8. Test a login before you enforce OIDC for a domain.

The issuer must publish an OIDC discovery document. Its `issuer` must exactly match the configured URL, including any trailing slash. Discovery, token, and signing-key endpoints must use HTTPS. Server requests reject private addresses and redirects.

PostHog requests `openid`, `profile`, and `email`. ID tokens must use RS256 and include an `email` claim. The email domain must belong to this configuration. PostHog does not use the userinfo endpoint to obtain this claim.

The token endpoint must support `client_secret_basic` or `client_secret_post` authentication.

Each verified domain can have only one complete OIDC configuration. An organization can use separate OIDC configurations for different domains. SAML and OIDC configurations can share a domain.

## Secrets and identity

PostHog encrypts client secrets at rest. The API does not return them. Leave the secret field empty when you edit a configuration to keep its saved secret. To rotate it, enter the new secret and save.

The API can remove a saved secret with `oidc_client_secret: ""`. This disables OIDC for that configuration. Deleting the configuration also disables it.

Turn off OIDC enforcement before you delete a configuration or remove its client secret. Enforcement does not fall back to password login if the configuration is missing.

Social identities use the configuration ID and the OIDC subject together. PostHog does not store provider access tokens or ID tokens in the social identity record.

## Release order

Deploy the billing feature definitions before the application changes. Existing customers receive OIDC through the normal billing sync. The settings UI remains behind `sso-settings-redesign`; this change does not alter the flag rollout or the legacy settings UI.

The existing identity-provider configuration events include the configuration scope. Use the `oidc` scope to check configuration adoption after release. Monitor the existing authentication errors during rollout.
