import { defineConfig } from 'vitest/config'

export default defineConfig({
    // See services/agent-shared/vitest.config.ts for why.
    css: { postcss: { plugins: [] } },
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 15_000,
        globals: true,
        // Test files share one Postgres (agent_runtime_queue_test). `reset()`
        // truncates the shared `agent_*` tables between cases, so running files
        // in parallel races on that shared state. Mirrors agent-shared + agent-tests.
        fileParallelism: false,
    },
})
