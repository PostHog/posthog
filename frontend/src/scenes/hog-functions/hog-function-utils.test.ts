import { CyclotronJobFilterPropertyFilter, CyclotronJobInputSchemaType, FilterLogicalOperator } from '~/types'

import {
    getHogFunctionDeliveryType,
    normalizeHogFunctionProperties,
    redactSecretHogFunctionInputs,
    serializeHogFunctionProperties,
} from './hog-function-utils'

const CLICKID: CyclotronJobFilterPropertyFilter = {
    key: 'clickid',
    value: 'is_set',
    operator: 'is_set',
    type: 'event',
} as CyclotronJobFilterPropertyFilter

// The diff-builder test covers schema-marked secrets end to end; this covers the entry-marked branch
// (a saved secret carries `secret: true` on the input entry itself, with no schema flag needed).
describe('redactSecretHogFunctionInputs', () => {
    it('redacts entry-marked secrets and leaves plain inputs untouched', () => {
        const redacted = redactSecretHogFunctionInputs(
            {
                token: { value: 'tok-cleartext', secret: true },
                url: { value: 'https://example.com' },
            },
            [] as CyclotronJobInputSchemaType[]
        )
        expect(redacted.token.value).toBe('[secret]')
        expect(redacted.url.value).toBe('https://example.com')
    })
})

// Guards the backward-compat contract for global property filters: a legacy flat list reads as AND,
// a group reads with its own operator, and only OR round-trips to the group shape — so a flat list
// stays flat (no churn for existing destinations) while an OR selection actually persists as OR.
describe('normalize/serialize hog function properties', () => {
    it('normalizes a flat list to an AND group', () => {
        expect(normalizeHogFunctionProperties([CLICKID])).toEqual({
            type: FilterLogicalOperator.And,
            values: [CLICKID],
        })
    })

    it('normalizes an empty/undefined value to an empty AND group', () => {
        expect(normalizeHogFunctionProperties(undefined)).toEqual({ type: FilterLogicalOperator.And, values: [] })
    })

    it('preserves the operator of a group', () => {
        const group = { type: FilterLogicalOperator.Or, values: [CLICKID] }
        expect(normalizeHogFunctionProperties(group)).toEqual(group)
    })

    it('serializes AND back to a flat list and OR to a group', () => {
        expect(serializeHogFunctionProperties(FilterLogicalOperator.And, [CLICKID])).toEqual([CLICKID])
        expect(serializeHogFunctionProperties(FilterLogicalOperator.Or, [CLICKID])).toEqual({
            type: FilterLogicalOperator.Or,
            values: [CLICKID],
        })
    })
})

describe('getHogFunctionDeliveryType', () => {
    it.each([
        ['batch-export-9', 'batch'],
        ['batch-export-AwsS3', 'batch'],
        ['plugin-7', 'realtime'],
        ['abc123', 'realtime'],
        ['template-slack', 'realtime'],
    ])('classifies %s as %s', (id, expected) => {
        expect(getHogFunctionDeliveryType({ id })).toBe(expected)
    })
})
