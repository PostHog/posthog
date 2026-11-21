import fs from 'fs'
import os from 'os'
import path from 'path'

import { logger } from '~/common/utils/logger'

import { createClickhouseHttpsAgent } from './clickhouse-config'

describe('createClickhouseHttpsAgent', () => {
    const pem = '-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n'
    let caPath: string

    beforeAll(() => {
        caPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'clickhouse-ca-')), 'ca.pem')
        fs.writeFileSync(caPath, pem)
    })

    afterAll(() => {
        fs.rmSync(path.dirname(caPath), { recursive: true })
    })

    it.each([
        { verify: false, ca: '', rejectUnauthorized: false, loadsCa: false, warns: false },
        { verify: true, ca: '', rejectUnauthorized: true, loadsCa: false, warns: false },
        { verify: true, ca: 'file', rejectUnauthorized: true, loadsCa: true, warns: false },
        { verify: false, ca: 'file', rejectUnauthorized: false, loadsCa: false, warns: true },
    ])('CLICKHOUSE_VERIFY=$verify with CLICKHOUSE_CA=$ca', ({ verify, ca, rejectUnauthorized, loadsCa, warns }) => {
        const warn = jest.spyOn(logger, 'warn').mockImplementation(() => undefined)
        const agent = createClickhouseHttpsAgent({
            CLICKHOUSE_VERIFY: verify,
            CLICKHOUSE_CA: ca ? caPath : '',
        })

        expect(agent.options.rejectUnauthorized).toBe(rejectUnauthorized)
        expect(agent.options.ca?.toString()).toBe(loadsCa ? pem : undefined)
        expect(warn).toHaveBeenCalledTimes(warns ? 1 : 0)
        warn.mockRestore()
    })

    it('fails when the CLICKHOUSE_CA file is missing', () => {
        expect(() =>
            createClickhouseHttpsAgent({ CLICKHOUSE_VERIFY: true, CLICKHOUSE_CA: `${caPath}.missing` })
        ).toThrow(/ENOENT/)
    })
})
