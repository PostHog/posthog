#!/usr/bin/env tsx
/**
 * One-off backfill: generate LLM summaries for terminal sessions that don't have
 * one yet (created before runner-inline summarization shipped, or where the
 * inline attempt failed). Reuses the runner's gateway summary model + the agent
 * DB queue. Resumable — successful rows stamp `summary_generated_at` and drop
 * out of `listTerminalUnsummarized`; an in-run `seen` set keeps un-summarizable
 * rows from looping forever.
 *
 *   pnpm tsx bin/backfill-summaries.ts [maxSessions=500] [batchSize=25]
 */

import { createAgentPool, createLogger, PgSessionQueue } from '@posthog/agent-shared'

import { loadAgentRunnerConfig } from '../src/config'
import { generateSessionSummary } from '../src/loop/summarize-session'
import { posthogAiGatewayModel } from '../src/models/ai-gateway-model'

const log = createLogger('agent-runner.backfill-summaries')

async function main(): Promise<void> {
    const config = loadAgentRunnerConfig()
    if (!config.useAiGateway || !config.posthogAiGatewayKey) {
        log.error('summary backfill requires the ai-gateway (AGENT_USE_AI_GATEWAY=1 + POSTHOG_AI_GATEWAY_KEY)')
        process.exit(1)
    }
    const max = Math.max(1, Number(process.argv[2] ?? 500))
    const batch = Math.max(1, Math.min(Number(process.argv[3] ?? 25), 100))

    const model = posthogAiGatewayModel({
        specModel: config.summaryModel,
        baseUrl: config.aiGatewayUrl,
        apiKey: config.posthogAiGatewayKey,
    })
    const pool = createAgentPool(config.agentDbUrl)
    const queue = new PgSessionQueue(pool)

    const seen = new Set<string>()
    let summarized = 0
    let skipped = 0
    try {
        while (summarized + skipped < max) {
            const sessions = await queue.listTerminalUnsummarized(batch)
            const fresh = sessions.filter((s) => !seen.has(s.id))
            if (fresh.length === 0) {
                break
            }
            for (const s of fresh) {
                seen.add(s.id)
                try {
                    const summary = await generateSessionSummary(model, s.conversation, {
                        apiKey: config.posthogAiGatewayKey,
                    })
                    if (summary) {
                        await queue.setSummary(s.id, summary)
                        summarized++
                    } else {
                        skipped++
                    }
                } catch (err) {
                    log.warn({ session: s.id, err: (err as Error)?.message }, 'summary.failed')
                    skipped++
                }
            }
            log.info({ summarized, skipped }, 'backfill.progress')
        }
    } finally {
        await pool.end()
    }
    log.info({ summarized, skipped }, 'backfill.complete')
}

main().catch((err) => {
    log.error({ err: (err as Error)?.message }, 'backfill.fatal')
    process.exit(1)
})
