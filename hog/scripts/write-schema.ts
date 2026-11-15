// Writes posthog.schema.json from the zod definitions in src/core/config.ts. Run `pnpm --filter
// @posthog/hog schema` after changing them; a test fails while the file is out of date.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { configSchema } from '../src/core/config'

writeFileSync(join(import.meta.dir, '..', 'posthog.schema.json'), `${JSON.stringify(configSchema(), null, 2)}\n`)
