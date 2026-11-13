import { blockStage, earlyBlock, writeBlock } from '../agents-md'
import { completed, runNext, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

export const agentsMd: Step = {
    isDone: async (run) =>
        completed(run, 'agents-md') && (await blockStage(run.ctx.runtime, run.scope.folder)) !== undefined,

    summary: (run) => {
        const changed = run.context.agentsMd?.filter((file) => file.status !== 'unchanged')
        return changed?.length
            ? `Added the PostHog section to ${changed.map((file) => file.path).join(' and ')}`
            : '`AGENTS.md` has the PostHog section'
    },

    async advance(run) {
        if (!run.input.next) {
            return runNext(
                'setup_agents_md_pending',
                `Run \`${SETUP_NEXT}\` to add the PostHog section to \`AGENTS.md\`.`
            )
        }

        run.context.agentsMd = await writeBlock(run.ctx.runtime, run.scope.folder, earlyBlock())
        await run.complete('agents-md')

        return undefined
    },
}
