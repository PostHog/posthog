// Writes tests/fixtures/stack-all-kinds/description.json from the fixture folder, after a build.
// stack.test.mjs fails while the file and the folder disagree.
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { createApiToolLibrary } from '@posthog/mcp/dist/cli-library.mjs'
import { formatDescription, loadStack } from '@posthog/sdk/stack'

const folder = fileURLToPath(new URL('../tests/fixtures/stack-all-kinds/', import.meta.url))
const result = await loadStack(folder, { validator: createApiToolLibrary() })
if (result.problems.some((problem) => problem.severity === 'error')) {
    console.error(JSON.stringify(result.problems, null, 2))
    process.exit(1)
}
writeFileSync(new URL('description.json', `file://${folder}`), formatDescription(result.description))
