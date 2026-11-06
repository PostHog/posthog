import { parseProviderIdToken } from '@/posthog/tokens'

import type { WorkloadProvider } from '../registry'

// The variable a job puts its token in when no supported provider issues it. GitLab jobs use the same name.
export const CUSTOM_ID_TOKEN_VARIABLE = 'HOG_ID_TOKEN'

// Any other OIDC issuer, which an admin trusts with the claims they name. hog can't ask such an issuer for a
// token, so the job passes one in, minted with the PostHog address as its audience.
export const CUSTOM_OIDC: WorkloadProvider = {
    key: 'custom',
    name: 'Custom OIDC provider',
    issuer: '',
    docsUrl: 'https://posthog.com/docs/api/workload-identity/custom',
    detect: (env) => !!env[CUSTOM_ID_TOKEN_VARIABLE],
    fetchToken: async (runtime) => {
        const token = runtime.env[CUSTOM_ID_TOKEN_VARIABLE]
        return token
            ? parseProviderIdToken(token, {
                  context: `${CUSTOM_ID_TOKEN_VARIABLE} doesn't hold an OIDC token.`,
                  hint: 'Set it to an ID token from your issuer, with the PostHog address as its audience.',
              })
            : undefined
    },
    missingTokenHint: `Set ${CUSTOM_ID_TOKEN_VARIABLE} in the job to an ID token from your issuer, with the PostHog address as its audience.`,
    configPaths: [],
    nameFromRemote: () => undefined,
    branchConditions: () => ({}),
    snippet: ({ host }) => `${CUSTOM_ID_TOKEN_VARIABLE}=<an ID token from your issuer, with the audience ${host}>`,
}
