import * as fs from 'fs'

import { expect, test } from '../../utils/playwright-test-core'

test.describe('Skip outer', () => {
    test.describe('Skip inner', () => {
        test('fails hard when executed', () => {
            if (process.env.QMATRIX_MARKER_SKIP) {
                fs.appendFileSync(process.env.QMATRIX_MARKER_SKIP, 'executed\n')
            }
            expect(1).toBe(2)
        })
    })
})
