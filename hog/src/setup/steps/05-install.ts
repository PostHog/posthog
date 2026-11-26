import { z } from 'zod'

import { SKILL_COMMANDS } from '@/core/skill-commands'
import { INGESTION_HOSTS, regionOf } from '@/posthog/host'
import { ProjectTokenSchema } from '@/posthog/tokens'

import { INSTALL_SKILL, type Product } from '../products'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { hasRead, SETUP_COMMAND, type SkillFile } from '../state'

export const SKILL_READ: SkillFile = { skill: INSTALL_SKILL, path: 'SKILL.md' }
export const RULES_READ: SkillFile = { skill: INSTALL_SKILL, path: 'references/COMMANDMENTS.md' }

const ProjectSchema = z.looseObject({ api_token: ProjectTokenSchema })

export function readCommand({ skill, path }: SkillFile): string {
    const name = skill.replace(/^posthog:/, '')
    return path === 'SKILL.md' ? SKILL_COMMANDS.read(name) : SKILL_COMMANDS.read(name, path)
}

async function fillInstallContext(run: SetupRun): Promise<void> {
    const [{ host }, api] = await Promise.all([run.requireLogin(), run.api()])
    const project = await api.get('', ProjectSchema)
    const region = regionOf(host)

    run.context.token = project.api_token
    run.context.apiHost = region ? INGESTION_HOSTS[region] : host
}

async function productReads(run: SetupRun): Promise<Product[]> {
    const products = await run.productsContext()
    return products.filter(
        (product) =>
            product.chosen && product.id !== 'product-analytics' && product.command.startsWith('hog skills read ')
    )
}

function productNote(picked: readonly Product[]): string {
    if (picked.length === 0) {
        return ''
    }
    const skills = picked.map((product) => `${product.label} with \`${product.command}\``).join(', ')
    return ` The user picked more products. Once PostHog is installed, read the skill for each one in full and set the product up in the app and in PostHog as it describes: ${skills}.`
}

// `hog skills read` records the reads. Both files count only when read whole.
export const install: Step = {
    summary: () => 'Installed PostHog with the install skill',

    async advance(run) {
        await fillInstallContext(run)

        const { state } = run
        const read = state !== undefined && hasRead(state, SKILL_READ) && hasRead(state, RULES_READ)
        if (read && run.startedOn('install')) {
            await run.complete('install')
            return undefined
        }

        const picked = await productReads(run)
        if (read) {
            return runNext(
                'setup_install_pending',
                `Install PostHog in this app as the skill describes, with \`context.token\` and \`context.apiHost\`.${productNote(picked)} Then run \`${SETUP_COMMAND}\`.`
            )
        }

        return {
            code: 'setup_skill_not_read',
            next: {
                kind: 'read',
                read: [readCommand(SKILL_READ), readCommand(RULES_READ), ...picked.map((product) => product.command)],
                command: SETUP_COMMAND,
                instructions: `Run ${picked.length > 0 ? 'the first two commands' : 'both commands'} and read each file in full, without \`--lines\`. Install PostHog in this app as the skill describes, with \`context.token\` and \`context.apiHost\`.${productNote(picked)} Then run \`${SETUP_COMMAND}\`.`,
            },
        }
    },
}
