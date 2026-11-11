import { z } from 'zod'

import { failureText, HogError } from '@/core/errors'
import { hasLogin, writeLoginToConfig } from '@/posthog/login/finish'

import { productIntent, productLabel } from '../products'
import { completed, runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

// A failed intent only costs PostHog a hint about what to show first, so it warns and setup goes on.
async function recordIntents(run: SetupRun): Promise<void> {
    const products = run.state?.products ?? []
    if (products.length === 0) {
        return
    }

    const api = await run.api()
    const results = await Promise.allSettled(
        products.map((id) =>
            api.patch(
                'add_product_intent/',
                { product_type: productIntent(id), metadata: { source: 'hog setup' } },
                z.unknown()
            )
        )
    )

    results.forEach((result, index) => {
        const id = products[index]
        if (result.status === 'rejected' && id !== undefined) {
            const reason = failureText(result.reason, run.ctx.mode.isCI)
            run.context.warnings.push(`PostHog didn't record your interest in ${productLabel(id)}: ${reason}`)
        }
    })
}

export const project: Step = {
    isDone: async (run) => {
        const [login, loaded] = await Promise.all([run.login(), run.ctx.config()])
        return completed(run, 'project') && login !== undefined && hasLogin(loaded?.config, login)
    },

    summary: async (run) => {
        const { host, projectId } = await run.requireLogin()
        return `posthog.json names project ${projectId} on ${host}`
    },

    async advance(run) {
        if (!run.input.next) {
            return runNext(
                'setup_project_pending',
                `Run \`${SETUP_NEXT}\` yourself. It names the project in posthog.json and tells PostHog which products the person picked.`
            )
        }

        const login = await run.requireLogin()
        const written = await writeLoginToConfig(run.ctx, login)
        if (written.status === 'failed') {
            throw new HogError(
                'setup_config_unwritable',
                `Writing ${written.path} failed: ${written.error ?? 'unknown error'}`,
                `Check that you can write to ${run.scope.folder}, then run \`${SETUP_NEXT}\` again.`
            )
        }

        if (written.status !== 'unchanged') {
            run.ctx.reload()
        }

        await recordIntents(run)
        await run.complete('project')

        return undefined
    },
}
