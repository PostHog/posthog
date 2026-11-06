import { parseProviderIdToken } from '@/posthog/tokens'

import type { WorkloadProvider } from './providers'

export const GITLAB_ID_TOKEN_VARIABLE = 'HOG_ID_TOKEN'

export const GITLAB: WorkloadProvider = {
    key: 'gitlab',
    name: 'GitLab',
    issuer: 'https://gitlab.com',
    docsUrl: 'https://posthog.com/docs/api/workload-identity/gitlab',
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
    configPaths: ['.gitlab-ci.yml'],
    nameFromRemote: (remote) => remote.match(/(?:^|[@/])gitlab\.com[:/](.+?)(?:\.git)?\/?$/)?.[1],
    branchConditions: (branch) => ({ ref: branch, ref_protected: 'true', ref_type: 'branch' }),
    environmentConditions: (environment) => ({ environment, environment_protected: 'true' }),
    snippet: ({ host, projectId }) =>
        [
            'your-job:',
            '  id_tokens:',
            `    ${GITLAB_ID_TOKEN_VARIABLE}: # lets hog get a PostHog token`,
            `      aud: ${host}`,
            '  variables:',
            `    HOG_HOST: ${host}`,
            `    HOG_PROJECT_ID: "${projectId}"`,
        ].join('\n'),
}
