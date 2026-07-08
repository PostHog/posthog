import { getHogFunctionDeliveryType } from './hog-function-utils'

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
