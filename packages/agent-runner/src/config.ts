import { z } from 'zod'

const ConfigSchema = z.object({
    queueDbUrl: z.string().min(1),
    queueName: z.string().default('default'),
    /** Base URL for the Django internal API (e.g. http://app:8000). */
    internalApiBaseUrl: z.string().min(1),
    internalApiSharedKey: z.string().optional(),
    redisUrl: z.string().optional(),
    /** Anthropic API key — only the runner reads secrets. */
    anthropicApiKey: z.string().optional(),
})

export type RunnerConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): RunnerConfig {
    return ConfigSchema.parse({
        queueDbUrl: env.AGENT_RUNTIME_QUEUE_DATABASE_URL,
        queueName: env.AGENT_RUNNER_QUEUE_NAME,
        internalApiBaseUrl: env.INTERNAL_API_BASE_URL,
        internalApiSharedKey: env.INTERNAL_API_SHARED_KEY,
        redisUrl: env.REDIS_URL,
        anthropicApiKey: env.ANTHROPIC_API_KEY,
    })
}
