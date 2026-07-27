import { defineConfig } from 'vitest/config'

export default defineConfig({
    // Backend service — no CSS to process. Without this stub, Vite walks up
    // to the repo-root postcss.config.js (Tailwind), which a filtered CI
    // install hasn't pulled @tailwindcss/postcss for.
    css: { postcss: { plugins: [] } },
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 10_000,
        globals: true,
        // Test files share one Postgres (agent_runtime_queue_test). `reset()`
        // truncates the shared `agent_*` tables between cases, so running files
        // in parallel races on that shared state. Mirrors agent-tests.
        fileParallelism: false,
    },
})
