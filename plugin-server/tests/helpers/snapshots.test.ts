import { UUIDT } from '~/utils/utils'

import { forSnapshot } from './snapshots'

describe('forSnapshot', () => {
    it('should replace UUIDs with placeholders', () => {
        const uuid1 = new UUIDT().toString()
        const uuid2 = new UUIDT().toString()
        const uuid3 = new UUIDT().toString()
        const obj = {
            id: uuid1,
            other: uuid3,
            list: [uuid1, uuid2],
            nested: {
                id: uuid2,
                list: [uuid1, uuid2],
            },
        }
        const result = forSnapshot(obj)
        expect(result).toMatchInlineSnapshot(`
            {
              "id": "<REPLACED-UUID-0>",
              "list": [
                "<REPLACED-UUID-0>",
                "<REPLACED-UUID-2>",
              ],
              "nested": {
                "id": "<REPLACED-UUID-2>",
                "list": [
                  "<REPLACED-UUID-0>",
                  "<REPLACED-UUID-2>",
                ],
              },
              "other": "<REPLACED-UUID-1>",
            }
        `)
    })

    it('should allow overriding keys', () => {
        const result = forSnapshot(
            {
                id: '123e4567-e89b-12d3-a456-426614174000',
                num: 1,
                timestamp: new Date(),
                leaveMeAlone: 'leave me alone',
            },
            {
                overrides: {
                    id: 'REPLACE_ME',
                    num: 'REPLACED_NUM',
                    timestamp: 'REPLACED_TIMESTAMP',
                },
            }
        )

        expect(result).toMatchInlineSnapshot(`
            {
              "id": "REPLACE_ME",
              "leaveMeAlone": "leave me alone",
              "num": "REPLACED_NUM",
              "timestamp": "REPLACED_TIMESTAMP",
            }
        `)
    })
})
