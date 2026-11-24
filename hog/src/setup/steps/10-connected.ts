import { finalBlock, writeBlock } from '../agents-md'
import { runNext, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

export const connected: Step = {
    summary: () => 'Wrote the final PostHog section to `AGENTS.md`',

    async advance(run) {
        const { ctx, state } = run
        if (!run.input.next) {
            return runNext(
                'setup_connect_pending',
                `Run \`${SETUP_NEXT}\` to finish setup and list the PostHog commands in \`AGENTS.md\`.`
            )
        }

        const [{ host, projectId }, products] = await Promise.all([run.requireLogin(), run.products()])
        const body = finalBlock({ host, projectId, products, chosen: state?.products ?? [] })
        run.context.agentsMd = await writeBlock(ctx.runtime, run.scope.folder, body)

        const startedAt = state?.startedAt ?? ctx.runtime.now()
        await run.complete('connected')
        ctx.telemetry.capture('hog setup completed', {
            products: state?.products ?? [],
            duration_ms: ctx.runtime.now() - startedAt,
        })

        return undefined
    },
}
