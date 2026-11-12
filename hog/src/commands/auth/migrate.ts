import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { parseJsonOrUndefined } from '@/core/json'
import { escapeControls } from '@/core/output'
import { PersonalAPIKey } from '@/posthog/access-key'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { CI_CREDENTIALS_HINT, DEFAULT_HOST, posthogFile } from '@/posthog/credentials'
import { parseHost } from '@/posthog/host'
import { parseProjectId } from '@/posthog/ids'
import { saveLogin } from '@/posthog/login/flow'
import { parsePersonalApiKey } from '@/posthog/tokens'

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

// The fields go through the brand factories below, so a bad value names what is wrong with it.
const LegacyCredentials = z.object({ token: z.unknown(), env_id: z.unknown(), host: z.unknown() })

// TODO(v1.1): drop this command. It exists so people moving from posthog-cli keep their key
// without logging in again, and hog reads the old file nowhere else.
export default defineCommand({
    description: 'Move the personal API key posthog-cli saved into hog',
    writes: true,
    refusesCI: { reason: 'moves a login saved on this machine', hint: CI_CREDENTIALS_HINT },
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
        const stored = parseJsonOrUndefined(text, LegacyCredentials)
        const failure = {
            code: 'invalid_legacy_credentials',
            context: `hog couldn't move the key in ${legacyFile}.`,
            hint: 'Run `hog auth login` to log in instead.',
        }
        const apiKey = parsePersonalApiKey(stored?.token, failure)
        const projectId = parseProjectId(stored?.env_id, failure)
        const host = typeof stored?.host === 'string' ? parseHost(stored.host, failure) : DEFAULT_HOST
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
