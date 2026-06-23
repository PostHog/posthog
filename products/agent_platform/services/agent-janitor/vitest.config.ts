import { defineConfig } from 'vitest/config'

export default defineConfig({
    // See services/agent-shared/vitest.config.ts for why.
    css: { postcss: { plugins: [] } },
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 15_000,
        globals: true,
        // Test files share the agent_runtime_queue_test PG. Running them in
        // parallel races on `node-pg-migrate`'s schema lock and on the
        // public-schema drop in `reset()`. Mirrors agent-shared + agent-tests.
        fileParallelism: false,
    },
})
