import { readFileSync } from 'fs'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { BILLED_USAGE_KEYS, ENTITLEMENTS_CONTRACT_RELATIVE_PATH } from './billing-usage-keys'

type EntitlementsContract = {
    usage_keys: Record<string, { quota_enforcement: 'posthog' | 'none' }>
}

describe('billing usage keys', () => {
    it('are all keys the vendored contract says PostHog enforces', () => {
        const contract = parseJSON(
            readFileSync(join(__dirname, '../../../..', ENTITLEMENTS_CONTRACT_RELATIVE_PATH), 'utf8')
        ) as EntitlementsContract
        const enforced = new Set(
            Object.entries(contract.usage_keys)
                .filter(([, entry]) => entry.quota_enforcement === 'posthog')
                .map(([key]) => key)
        )

        expect(BILLED_USAGE_KEYS.filter((key) => !enforced.has(key))).toEqual([])
    })
})
