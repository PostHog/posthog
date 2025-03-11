import { UUIDT } from '~/src/utils/utils'

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
})
