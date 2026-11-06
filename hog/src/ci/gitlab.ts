import { parseProviderIdToken } from '@/posthog/tokens'

import type { WorkloadProvider } from './providers'

// The job's `id_tokens` entry `hog ci setup` prints. GitLab puts the token in this variable.
export const GITLAB_ID_TOKEN_VARIABLE = 'HOG_ID_TOKEN'

export const GITLAB: WorkloadProvider = {
    key: 'gitlab',
    name: 'GitLab',
    issuer: 'https://gitlab.com',
    docsUrl: 'https://posthog.com/docs/api/workload-identity/gitlab',
    // Self-managed GitLab sets CI_SERVER_URL to its own address, and its tokens come from that issuer.
    detect: (env) => env.GITLAB_CI === 'true' && env.CI_SERVER_URL === 'https://gitlab.com',
    // GitLab fixes the audience in the job's config, so hog can't ask for one. The exchange refuses a
    // token whose audience isn't the PostHog host, and its error names the audience it expects.
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
    nameFromRemote: (remote) => remote.match(/gitlab\.com[:/](.+?)(?:\.git)?\/?$/)?.[1],
    // GitLab's ref claim is the short branch name. A merge request pipeline from a fork carries the
    // fork's project_id, so unlike GitHub the branch alone can't trust fork code.
    branchConditions: (branch) => ({ ref: branch, ref_type: 'branch' }),
    environmentConditions: (environment) => ({ environment }),
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
