import { defineConfig } from 'vitest/config'

export default defineConfig({
    test: {
        globals: true,
        environment: 'node',
        include: ['tests/integration/**/*.integration.test.ts'],
        testTimeout: 20000,
        hookTimeout: 20000,
        sequence: { concurrent: false },
    },
})
