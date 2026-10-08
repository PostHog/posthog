import { defineConfig } from '@playwright/test'

export default defineConfig({
    testDir: '.',
    testMatch: 'bootstrap.spec.ts',
    timeout: 60000,
    retries: 0,
    workers: 1,
    reporter: 'list',
})
