import { z } from 'zod'

import { INGESTION_HOSTS, regionOf } from '@/posthog/host'
import { ProjectTokenSchema } from '@/posthog/tokens'

import { INSTALL_SKILL } from '../products'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { hasRead, SETUP_NEXT, type SkillFile } from '../state'

export const SKILL_READ: SkillFile = { skill: INSTALL_SKILL, path: 'SKILL.md' }
export const RULES_READ: SkillFile = { skill: INSTALL_SKILL, path: 'references/COMMANDMENTS.md' }

const ProjectSchema = z.looseObject({ api_token: ProjectTokenSchema })

export function readCommand({ skill, path }: SkillFile): string {
    return path === 'SKILL.md' ? `hog learn ${skill}` : `hog learn ${skill} ${path}`
}

async function fillInstallContext(run: SetupRun): Promise<void> {
    const [{ host }, api] = await Promise.all([run.requireLogin(), run.api()])
    const project = await api.get('', ProjectSchema)
    const region = regionOf(host)

    run.context.token = project.api_token
    run.context.apiHost = region ? INGESTION_HOSTS[region] : host
}

// `hog learn` records the reads. Both files count only when read whole.
export const install: Step = {
    summary: () => 'Read the install skill and installed PostHog',

    async advance(run) {
        await fillInstallContext(run)

        const { state } = run
        const read = state !== undefined && hasRead(state, SKILL_READ) && hasRead(state, RULES_READ)
        if (read && run.startedOn('install')) {
            await run.complete('install')
            return undefined
        }

        if (read) {
            return runNext(
                'setup_install_pending',
                `Install PostHog in this app as the skill says, with the project token and host in context. Then run \`${SETUP_NEXT}\` yourself.`
            )
        }

        return {
            code: 'setup_skill_not_read',
            next: {
                kind: 'read',
                read: [readCommand(SKILL_READ), readCommand(RULES_READ)],
                command: SETUP_NEXT,
                instructions: `Run both commands, and follow the skill to install PostHog in this app with the project token and host in context. Then run \`${SETUP_NEXT}\` yourself.`,
            },
        }
    },
}
