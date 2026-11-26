import { z } from 'zod'

import { failureText, HogError } from '@/core/errors'
import { hasLogin, writeLoginToConfig } from '@/posthog/login/finish'

import { productIntent, productLabel, type ProductId } from '../products'
import { completed, runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_COMMAND } from '../state'

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

const ENABLEMENT: Partial<Record<ProductId, string>> = {
    'session-replay': 'session_replay',
    'error-tracking': 'error_tracking',
}

const EnablementSchema = z.object({ results: z.record(z.string(), z.string()) })

// Picking session replay means recording sessions, so setup turns it on rather than leave it to the
// agent. A failure only warns: the agent can still turn it on with `hog api`.
async function enableProducts(run: SetupRun): Promise<void> {
    const picked = (run.state?.products ?? []).filter((id) => ENABLEMENT[id] !== undefined)
    if (picked.length === 0) {
        return
    }

    try {
        const [api, { projectId }] = await Promise.all([run.api(), run.requireLogin()])
        // PostHog serves this only under the project, not the environment.
        await api.post(
            `/api/projects/${projectId}/product_enablement/`,
            { products: picked.map((id) => ENABLEMENT[id]) },
            EnablementSchema
        )
        run.context.enabled = picked.map(productLabel)
    } catch (error) {
        const reason = failureText(error, run.ctx.mode.isCI)
        run.context.warnings.push(`hog couldn't turn on ${picked.map(productLabel).join(' and ')}: ${reason}`)
    }
}

export const project: Step = {
    isDone: async (run) => {
        const [login, loaded] = await Promise.all([run.login(), run.ctx.config()])
        return completed(run, 'project') && login !== undefined && hasLogin(loaded?.config, login)
    },

    summary: async (run) => {
        const { host, projectId } = await run.requireLogin()
        return `Saved project ${projectId} on ${host} in \`posthog.json\``
    },

    async advance(run) {
        if (!run.input.next) {
            return runNext(
                'setup_project_pending',
                `Run \`${SETUP_COMMAND}\` to save the project in \`posthog.json\` and send the products the user picked to PostHog.`
            )
        }

        const login = await run.requireLogin()
        const written = await writeLoginToConfig(run.ctx, login)
        if (written.status === 'failed') {
            throw new HogError(
                'setup_config_unwritable',
                `Couldn't write ${written.path}: ${written.error ?? 'unknown error'}`,
                `Check that you can write to ${run.scope.folder}, then run \`${SETUP_COMMAND}\` again.`
            )
        }

        if (written.status !== 'unchanged') {
            run.ctx.reload()
        }

        await recordIntents(run)
        await enableProducts(run)
        await run.complete('project')

        return undefined
    },
}
