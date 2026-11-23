import { EXIT_NEEDS_PERSON, exitCodeFor, HogError } from '@/core/errors'
import { ApiError } from '@/posthog/api'
import { addToKeyHint, stepUpCommand, workloadScopesHint } from '@/posthog/scope-challenge'

export const internalWords = /\b(?:terraform|opentofu|tofu|provider|state|plan|apply|hcl|resource address)\b/i

const guidance: Readonly<Record<string, readonly [string, string]>> = {
    stack_moved: [
        'The stack changed since this diff was made.',
        'Run hog diff again and review the new changes before pushing.',
    ],
    stack_locked: ['Another push is using this stack.', 'Wait for it to finish, then run hog diff again.'],
    diff_not_ready: ['This diff has not finished.', 'Run hog diff --wait <id> before pushing it.'],
    diff_pushed: ['This diff was already pushed.', 'Run hog push --wait <id> to see its result.'],
    diff_expired: ['This diff has expired.', 'Run hog diff again and review the new diff.'],
    claimed_by_other_stack: [
        'Another stack manages this entity.',
        'Edit its definition in the owning stack or release its binding there before adopting it.',
    ],
    entity_already_bound: [
        'This entity already has a binding.',
        'Use its existing definition or release the existing binding before adopting it.',
    ],
    key_already_bound: [
        'Another entity already uses this definition key.',
        'Choose a distinct key and run hog diff again.',
    ],
    too_many_removals: [
        'This push removes or recreates more entities than the limit allows.',
        'Ask a person to review the removals and recreations in the diff and run hog push --diff <id> --max-removals <count> at a terminal, where hog asks them to confirm.',
    ],
    invalid_stack_name: [
        'The stack name is invalid.',
        'Choose a lowercase stack name in posthog.json and pass it with --stack.',
    ],
    kind_not_adoptable: ['This kind cannot be adopted.', 'Choose a supported kind with hog pull --adopt <kind>.'],
    stack_not_found: [
        'PostHog could not find this stack.',
        'Check the stack and environment in posthog.json, then run hog diff.',
    ],
    diff_not_found: ['PostHog could not find this diff.', 'Check the ID and stack, or run hog diff to get a new ID.'],
    binding_not_found: ['PostHog could not find the binding.', 'Check the stack and entity, then run hog diff again.'],
    user_required: [
        'This operation needs a signed-in user.',
        'Run hog auth login or use a personal API key with access to the project.',
    ],
    push_uncertain: [
        'PostHog could not confirm the outcome of the last push, so the stack takes no push until a person reconciles it.',
        'Run hog diff and read its warnings about entities the push may have created. Then a person runs hog stack reconcile --diff <id> with that diff before it is pushed.',
    ],
    nothing_to_reconcile: [
        'This stack has no push with an unknown outcome to reconcile.',
        'Push the diff with hog push --diff <id>, or run hog diff to review it again.',
    ],
    credential_not_supported: [
        'Stacks cannot run with this kind of credential.',
        "Log in with hog auth login, or use a personal API key or a CI job's OIDC token, then run the command again.",
    ],
    impersonated_push: [
        'An impersonated session cannot push this diff.',
        'End impersonation and sign in as yourself before pushing.',
    ],
    record_missing: [
        'PostHog could not read the last saved stack record.',
        'Contact support to recover the stack before pushing again.',
    ],
    run_timed_out: ['The stack operation timed out.', 'Run hog diff again to review what changed before another push.'],
    entity_not_found: [
        'PostHog could not find the selected entity.',
        'List the available entities with hog pull --adopt <kind> and check the ID.',
    ],
    stacks_unavailable: [
        'Stacks are unavailable on this PostHog instance.',
        'Contact PostHog support or your instance administrator to enable stacks.',
    ],
    secret_missing: [
        'The stack is missing a secret used by a definition.',
        'Set the missing name with hog stack secret set NAME, then run hog diff again.',
    ],
    secret_literal: [
        'A definition contains a secret value.',
        "Store it with hog stack secret set NAME, replace the value with secret('NAME'), and run hog diff again.",
    ],
    managed_in_code: [
        'This entity is managed in code.',
        'Edit its definition in the owning repository and run hog diff.',
    ],
    secret_not_found: ['The stack does not hold this secret.', 'Run hog stack secret list and check the name.'],
    invalid_secret_name: [
        'This secret name is invalid.',
        'Use up to 100 letters, numbers or underscores, starting with a letter or underscore.',
    ],
    secret_too_large: ['The secret is too large.', 'Pass a secret of at most 64 KiB.'],
    duplicate_definition: [
        'Two definitions use the same key.',
        'Give each definition of that kind its own key and run hog check.',
    ],
    invalid_key: ['The definition key is invalid.', 'Check the key for this kind and run hog check.'],
    too_many_definitions: [
        'This stack has too many definitions.',
        'Split the definitions into smaller stacks and run hog diff again.',
    ],
    definition_too_large: [
        'The description exceeds the size limit.',
        'Split the definitions into smaller stacks and run hog diff again.',
    ],
    definition_too_deep: [
        'Fields in this definition are nested too deeply.',
        'Simplify the nested values and run hog check.',
    ],
    invalid_definition: ['PostHog could not read a definition.', 'Review its fields and run hog check.'],
    kind_unsupported: [
        'PostHog cannot manage this definition kind.',
        'Check the kind and the version of PostHog, then run hog check.',
    ],
    caller_unavailable: [
        'PostHog could not authorize the person who started this run.',
        'Sign in with hog auth login and start a new diff.',
    ],
    runner_unavailable: ['PostHog could not start the stack operation.', 'Wait a few minutes and run hog diff again.'],
    invalid_input: [
        'PostHog could not read the request.',
        'Check the options and the definitions before running the command again.',
    ],
    context_pages_not_enabled: [
        'This stack defines context pages, which every project in the organization shares, and the stack may not manage them yet.',
        'Ask an organization admin to run hog stack context-pages enable for this stack, then run hog diff again.',
    ],
    organization_admin_required: [
        'Only an organization admin can change this.',
        'Ask an organization admin to run the same command.',
    ],
    kind_not_listable: [
        'PostHog cannot list entities of this kind to adopt, because they belong to the whole organization.',
        "Write the definition by hand with the entity's key, then run hog diff, which adopts the existing entity.",
    ],
    context_layer_not_enabled: [
        'The context layer is not on for this project.',
        'Ask a project admin to turn it on in PostHog, then run hog diff again.',
    ],
    context_page_managed_twice: [
        'Two definitions in this organization manage the same context page path.',
        'Keep one definition for the path, in this stack or the other one, then run hog diff again.',
    ],
    repository_not_connected: [
        "The stack's repository has no GitHub connection in this project.",
        'Ask a project admin to connect the repository in PostHog, or edit the definition and open a pull request yourself.',
    ],
    tasks_unavailable: [
        'This project cannot start cloud tasks.',
        'Edit the definition and open a pull request yourself, or ask a project admin to turn on cloud tasks.',
    ],
    context_page_write_uncertain: [
        'PostHog may have saved a context page before the push stopped.',
        'Ask a person to check the page in PostHog and run hog diff before anything else is pushed.',
    ],
}

export function stackGuidance(code: string): readonly [string, string] | undefined {
    return Object.hasOwn(guidance, code) ? guidance[code] : undefined
}

export function movedError(): HogError {
    const [message, hint] = guidance.stack_moved!
    return new HogError('stack_moved', message, hint)
}

export function stackApiFailure(
    error: ApiError,
    fallbackScope: string,
    credentialKind: string,
    host: string,
    confidential: boolean,
    declared?: string[]
): HogError {
    const status = error.status
    // The API client made these from PostHog's insufficient_scope challenge, after any step-up, with the hint every command uses.
    // A managed_in_code refusal already names the file to edit.
    const fromChallenge =
        ['step_up_required', 'missing_scopes'].includes(error.code) && error.exitCode === EXIT_NEEDS_PERSON
    if (fromChallenge || (error.code === 'managed_in_code' && error.details?.stack !== undefined)) {
        return error
    }
    if (['permission_denied', 'missing_scopes'].includes(error.code) && status === 403) {
        // A personal API key gets no challenge, only the scopes under `extra`.
        const required = confidential ? [fallbackScope] : declared?.length ? [...new Set(declared)] : [fallbackScope]
        const hint =
            credentialKind === 'workload'
                ? workloadScopesHint(required)
                : credentialKind === 'oauth'
                  ? `Run \`${stepUpCommand(required, host)}\` and retry.`
                  : addToKeyHint(required)
        return new HogError(
            error.code,
            `This command needs ${required.join(', ')} in this project.`,
            hint,
            EXIT_NEEDS_PERSON,
            { status, scopes: required }
        )
    }
    const known = stackGuidance(error.code)
    if (known) {
        const detail =
            !confidential &&
            error.code !== 'secret_literal' &&
            error.serverDetail &&
            !internalWords.test(error.serverDetail)
                ? error.serverDetail
                : undefined
        const exitCode = exitCodeFor(error.code) === EXIT_NEEDS_PERSON ? EXIT_NEEDS_PERSON : error.exitCode
        return new HogError(error.code, known[0], known[1], exitCode, { status }, detail)
    }
    if (confidential) {
        return new HogError(
            'secret_request_failed',
            'PostHog could not complete this secret request.',
            'Check your connection and access to the stack, then retry.',
            error.exitCode,
            { status }
        )
    }
    return new ApiError(
        status,
        /^[a-z][a-z0-9_]*$/.test(error.code) && !internalWords.test(error.code) ? error.code : 'stack_failed',
        error.message,
        {
            hint: error.hint ?? 'Check the stack and project, then run hog diff again.',
            exitCode: error.exitCode,
            details: error.details,
            serverDetail:
                error.serverDetail && !internalWords.test(error.serverDetail) ? error.serverDetail : undefined,
        }
    )
}
