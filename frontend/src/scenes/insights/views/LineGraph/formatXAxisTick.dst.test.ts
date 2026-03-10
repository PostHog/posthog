import { execSync } from 'child_process'
import path from 'path'

describe('createXAxisTickCallback (DST)', () => {
    it('does not shift dates around US DST spring-forward transition', () => {
        // Jest's config sets TZ=UTC before test files load, so the DST bug
        // can't be reproduced in-process. Run the real test in a subprocess
        // with TZ=America/New_York — jest.config.ts respects a pre-set TZ.
        const testFile = path.resolve(__dirname, 'formatXAxisTick.dst.inner.test.ts')
        const jestBin = path.resolve(__dirname, '../../../../../node_modules/.bin/jest')
        const cwd = path.resolve(__dirname, '../../../../..')
        const cmd = `TZ=America/New_York ${jestBin} ${testFile} --no-coverage --no-cache`
        execSync(cmd, { cwd, timeout: 30000, stdio: 'pipe' })
    }, 30000)
})
