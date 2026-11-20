import { chmodSync, mkdtempSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { devConfigOf } from './config'

describe('devConfigOf', () => {
    const keyFile = path.join(mkdtempSync(path.join(os.tmpdir(), 'dev-target-')), 'key')
    writeFileSync(keyFile, 'phx_test\n')
    const env = {
        DEV_TARGET_HOST: 'https://dev.example.com',
        DEV_TARGET_CAPTURE: 'https://capture.example.com/',
        DEV_TARGET_OFFERS_TEAM_ID: '1',
        DEV_TARGET_OFFERS_TOKEN: 'phc_test',
        DEV_TARGET_WORKFLOW_ID: '0190f6a2-0000-7000-8000-000000000001',
        DEV_TARGET_RECEIPTS_TEAM_ID: '2',
        DEV_TARGET_KEY_FILE: keyFile,
    }

    beforeEach(() => chmodSync(keyFile, 0o600))

    it('reads the target from the environment and the key from its file', () => {
        expect(devConfigOf(env)).toEqual({
            host: 'https://dev.example.com',
            capture: 'https://capture.example.com',
            offers: { teamId: 1, token: 'phc_test', workflowId: '0190f6a2-0000-7000-8000-000000000001' },
            receiptsTeamId: 2,
            key: 'phx_test',
        })
    })

    it.each<[string, Record<string, string | undefined>, string]>([
        [
            'missing settings',
            { DEV_TARGET_HOST: undefined, DEV_TARGET_KEY_FILE: '' },
            'needs DEV_TARGET_HOST, DEV_TARGET_KEY_FILE',
        ],
        [
            'a host over plain http',
            { DEV_TARGET_HOST: 'http://dev.example.com' },
            'DEV_TARGET_HOST must be an https URL',
        ],
        ['a project id that is not one', { DEV_TARGET_RECEIPTS_TEAM_ID: '2a' }, 'must be a project id'],
        ['a blank project token', { DEV_TARGET_OFFERS_TOKEN: '  ' }, 'DEV_TARGET_OFFERS_TOKEN holds no key'],
        ['a workflow id that is not one', { DEV_TARGET_WORKFLOW_ID: 'flow-1' }, 'must be a workflow id'],
    ])('refuses %s', (_name, change, message) => {
        expect(() => devConfigOf({ ...env, ...change })).toThrow(message)
    })

    it('refuses an empty key file', () => {
        const empty = path.join(path.dirname(keyFile), 'empty')
        writeFileSync(empty, '\n', { mode: 0o600 })

        expect(() => devConfigOf({ ...env, DEV_TARGET_KEY_FILE: empty })).toThrow('DEV_TARGET_KEY_FILE holds no key')
    })

    it('refuses a key file other users can read', () => {
        chmodSync(keyFile, 0o644)

        expect(() => devConfigOf(env)).toThrow('readable by its owner only')
    })
})
