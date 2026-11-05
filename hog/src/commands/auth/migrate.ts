import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { PersonalAPIKey } from '@/posthog/access-key'
import { parseJson } from '@/posthog/credential-store/helpers'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { checkApiKey, checkHost, checkProjectId, DEFAULT_HOST, posthogFile } from '@/posthog/credentials'
import { trimHost } from '@/posthog/host'
import { saveLogin } from '@/posthog/login/flow'

type MigrateResult =
    | {
          status: 'migrated'
          host: string
          projectId: string
          store: StoreChoice
          credentialsPath: string | null
          keychainError: string | null
          // The file the key came from, which hog leaves as it was.
          legacyFile: string
      }
    | { status: 'nothing_to_migrate'; legacyFile: string; next: string }

// TODO(v1.1): drop this command. It exists so people moving from posthog-cli keep their key
// without logging in again, and hog reads the old file nowhere else.
export default defineCommand({
    description: 'Move the personal API key posthog-cli saved into hog',
    writes: true,
    notes: [
        'Reads ~/.posthog/credentials.json, the file `posthog-cli login` writes, and saves its key the way `hog auth login` saves one.',
        'hog never reads that file otherwise, and leaves it as it is.',
    ].join('\n'),
    examples: ['hog auth migrate'],

    async run({ ctx }): Promise<MigrateResult> {
        const { runtime } = ctx
        const legacyFile = posthogFile(runtime, 'credentials.json')
        let text: string
        try {
            text = await runtime.readFile(legacyFile)
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
                return { status: 'nothing_to_migrate', legacyFile, next: 'hog auth login' }
            }
            throw error
        }
        const stored = parseJson(text) as { token?: unknown; env_id?: unknown; host?: unknown } | null | undefined
        const apiKey = typeof stored?.token === 'string' ? stored.token : ''
        const projectId = stored?.env_id === undefined ? '' : String(stored.env_id)
        const host = trimHost(typeof stored?.host === 'string' ? stored.host : DEFAULT_HOST)
        const problem = checkApiKey(apiKey) ?? checkProjectId(projectId) ?? checkHost(host)
        if (problem) {
            throw new HogError(
                'invalid_legacy_credentials',
                `hog couldn't move the key in ${legacyFile}. ${problem}`,
                'Run `hog auth login` to log in instead.'
            )
        }
        const key = new PersonalAPIKey({ host, projectId, apiKey })
        const loggedIn = await saveLogin(runtime, key)
        const { store, credentialsPath, keychainError } = loggedIn
        return { status: 'migrated', host, projectId, store, credentialsPath, keychainError, legacyFile }
    },

    human({ result, out }) {
        if (result.status === 'nothing_to_migrate') {
            out.line(`There is nothing to move: ${result.legacyFile} doesn't exist.`)
            out.line(`Run ${out.style(result.next, 'bold')} to log in.`)
            return
        }
        const where = result.store === 'keychain' ? 'the system keychain' : (result.credentialsPath ?? '')
        out.line(
            `${out.style('Moved', 'green', 'bold')} the personal API key for ${escapeControls(result.host)}, project ${result.projectId}, into ${where}.`
        )
        if (result.keychainError) {
            out.line(out.style(`${escapeControls(result.keychainError).replace(/\.$/, '')}.`, 'yellow'))
        }
        out.line(
            out.style(`hog no longer reads ${result.legacyFile}. Delete it once posthog-cli doesn't need it.`, 'dim')
        )
    },
})
