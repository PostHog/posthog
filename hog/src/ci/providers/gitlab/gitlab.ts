import { parseProviderIdToken } from '@/posthog/tokens'

import type { WorkloadProvider } from '../registry'

const GITLAB_ID_TOKEN_VARIABLE = 'HOG_ID_TOKEN'

export const GITLAB: WorkloadProvider = {
    key: 'gitlab',
    name: 'GitLab',
    // Self-managed GitLab sets CI_SERVER_URL to its own address, and its tokens come from that issuer.
    detect: (env) => env.GITLAB_CI === 'true' && env.CI_SERVER_URL === 'https://gitlab.com',
    // GitLab fixes the audience in the job's config. A wrong one gets an exchange error that names the right one.
    fetchToken: async (runtime) => {
        const token = runtime.env[GITLAB_ID_TOKEN_VARIABLE]
        return token
            ? parseProviderIdToken(token, {
                  context: `${GITLAB_ID_TOKEN_VARIABLE} doesn't hold a GitLab ID token.`,
                  hint: 'Set it with an `id_tokens` entry in the job. Run `hog ci setup` on your machine for the snippet.',
              })
            : undefined
    },
    missingTokenHint: `Add an \`id_tokens\` entry named ${GITLAB_ID_TOKEN_VARIABLE} to the job, with the PostHog address as its \`aud\`. Run \`hog ci setup\` on your machine for the snippet.`,
    configPath: '.gitlab-ci.yml',
    nameFromRemote: (remote) =>
        remote
            .match(
                /^(?:[a-z+]+:\/\/(?:[^@/]*@)?gitlab\.com(?::\d+)?\/|(?:[^@:/]+@)?gitlab\.com:)([\w.-]+(?:\/[\w.-]+)+)\/?$/i
            )?.[1]
            ?.replace(/\.git$/, ''),
}
