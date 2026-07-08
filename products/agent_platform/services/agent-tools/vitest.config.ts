import { defineConfig } from 'vitest/config'

export default defineConfig({
    // See services/agent-shared/vitest.config.ts for why.
    css: { postcss: { plugins: [] } },
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 10_000,
        globals: true,
    },
})
