import { type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'
import { readCommand, RULES_READ } from './5-install'

const QUESTION = 'Did you check your changes against every install rule and fix any that break one?'

export const review: Step = {
    summary: () => 'Checked the changes against the install rules',

    async advance(run) {
        const prompts = run.input.next ? run.ctx.prompts : undefined
        const reviewed = run.input.reviewed ?? (await prompts?.confirm(QUESTION))

        if (reviewed) {
            await run.complete('review')
            return undefined
        }

        return {
            code: 'setup_not_reviewed',
            next: {
                kind: 'read',
                read: [readCommand(RULES_READ)],
                command: `${SETUP_NEXT} --reviewed`,
                instructions: `Read the rules again and check your changes against each one. Fix any change that breaks a rule. Then run \`${SETUP_NEXT} --reviewed\`.`,
            },
        }
    },
}
