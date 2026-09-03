import * as fs from 'fs'
import * as path from 'path'

const REPO_ROOT = path.resolve(__dirname, '../../..')
const GENERATED_JSON = 'frontend/src/taxonomy/core-filter-definitions-by-group.json'

describe('core filter definitions JSON', () => {
    test('stays in the oxfmt ignore list, so the Python generator owns its bytes', () => {
        const config = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, '.oxfmtrc.json'), 'utf-8'))
        const ignorePatterns: string[] = config.ignorePatterns ?? []

        const missingEntryHint = ignorePatterns.includes(GENERATED_JSON)
            ? undefined
            : `${GENERATED_JSON} is missing from ignorePatterns in .oxfmtrc.json. lint-staged pipes staged JSON ` +
              'through `bin/hogli format:yaml` (oxfmt), and that entry is the only thing keeping oxfmt off ' +
              'this file. Without it the committed bytes stop matching the json.dump output of ' +
              'bin/build-taxonomy-json.py, so the taxonomy drift check in ci-python.yml fails for whoever ' +
              'next edits posthog/taxonomy/taxonomy.py. Restore the entry rather than reformatting the JSON.'

        expect(missingEntryHint).toBeUndefined()
    })
})
