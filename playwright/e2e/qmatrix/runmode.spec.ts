import * as fs from 'fs'

import { expect, test } from '../../utils/playwright-test-core'

test('runmode still executes', () => {
    if (process.env.QMATRIX_MARKER_RUN) {
        fs.appendFileSync(process.env.QMATRIX_MARKER_RUN, 'executed\n')
    }
    expect(1).toBe(2)
})
