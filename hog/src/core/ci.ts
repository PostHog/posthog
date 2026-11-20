import type { Env } from './runtime'

type EnvCheck = (env: Env) => boolean
const has =
    (name: string): EnvCheck =>
    (env) =>
        Boolean(env[name])

// First match wins. Platforms that also set the variables of another one come first: Depot CI
// before GitHub Actions, Harness and Woodpecker before Drone. Vercel sets VERCEL outside builds too.
const CI_PROVIDERS: ReadonlyArray<readonly [provider: string, check: EnvCheck]> = [
    ['depot-ci', has('DEPOT_JOB_URL')],
    ['harness', has('HARNESS_BUILD_ID')],
    ['woodpecker', (env) => env.CI === 'woodpecker'],
    ['github-actions', has('GITHUB_ACTIONS')],
    ['gitlab', has('GITLAB_CI')],
    ['circleci', has('CIRCLECI')],
    ['buildkite', has('BUILDKITE')],
    ['jenkins', has('JENKINS_URL')],
    ['travis', has('TRAVIS')],
    ['bitbucket', has('BITBUCKET_COMMIT')],
    ['azure-pipelines', has('TF_BUILD')],
    ['aws-codebuild', has('CODEBUILD_BUILD_ARN')],
    ['google-cloud-build', has('BUILDER_OUTPUT')],
    ['vercel', (env) => Boolean(env.VERCEL && env.CI)],
    ['netlify', has('NETLIFY')],
    ['cloudflare-pages', has('CF_PAGES')],
    ['cloudflare-workers', has('WORKERS_CI')],
    ['render', has('RENDER')],
    ['railway', has('RAILWAY_SERVICE_ID')],
    ['heroku-ci', has('HEROKU_TEST_RUN_ID')],
    ['expo-eas', has('EAS_BUILD')],
    ['bitrise', has('BITRISE_IO')],
    ['xcode-cloud', has('CI_XCODE_CLOUD')],
    ['codemagic', has('CM_BUILD_ID')],
    ['semaphore', has('SEMAPHORE')],
    ['drone', has('DRONE')],
    ['teamcity', has('TEAMCITY_VERSION')],
    ['appveyor', has('APPVEYOR')],
]

// Vendors that run GitHub Actions jobs on their own machines. Some of these variables hold tokens,
// so hog only checks that they are set.
const runnerName =
    (prefix: string): EnvCheck =>
    (env) =>
        env.RUNNER_NAME?.startsWith(prefix) === true
const CI_RUNNERS: ReadonlyArray<readonly [runner: string, check: EnvCheck]> = [
    ['depot', (env) => has('DEPOT_ORG_ID')(env) || runnerName('depot-')(env)],
    ['blacksmith', has('BLACKSMITH_VM_ID')],
    ['namespace', (env) => has('NSC_CACHE_PATH')(env) || runnerName('nsc-runner-')(env)],
    ['warpbuild', has('WARPBUILD_RUNNER_VERIFICATION_TOKEN')],
    ['ubicloud', has('UBICLOUD_CACHE_URL')],
    ['runs-on', has('RUNS_ON_RUNNER_NAME')],
    ['cirun', runnerName('cirun-')],
]

export function detectCi(env: Env): { provider: string | null; runner: string | null } {
    const provider = CI_PROVIDERS.find(([, check]) => check(env))?.[0] ?? null
    const runner = CI_RUNNERS.find(([, check]) => check(env))?.[0] ?? env.RUNNER_ENVIRONMENT ?? null
    return { provider, runner }
}

function isTruthy(value: string | undefined): boolean {
    return value !== undefined && value !== '' && value !== '0' && value.toLowerCase() !== 'false'
}

// Most CI services export CI, but Jenkins, Azure Pipelines and AWS CodeBuild only set their own
// variables, so a known provider counts too.
export function isRunningInCI(env: Env): boolean {
    return isTruthy(env.CI) || detectCi(env).provider !== null
}
