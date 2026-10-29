import { defineCommand } from '@/core/command'
import { configSchema, SCHEMA_URL } from '@/core/config'

export default defineCommand({
    description: 'Print the JSON schema for posthog.json',
    allowsInvalidConfig: true,
    notes: `Editors validate posthog.json when it starts with "$schema": "${SCHEMA_URL}".`,
    examples: ['hog config schema > posthog.schema.json'],

    run: () => configSchema(),
})
