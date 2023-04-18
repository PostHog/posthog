import { compressToString, decompressFromString } from './utils'

// NOTE: This was copied from the output of the related python ingestion code
const compressedData =
    'H4sIAFUyHGQC/1WOwQ6CMBBE36cYzh5QFMWf8AOMB6KQ9IASC4nE+OvqlK4kpNl2OjO7O9/PiRcJHQMtldCBBRlL3QlXSimlscHnudPz4DJ5V+ZtpXic/E7oJhz1OP9pv5wdhXUMxgUmNc5p5zxDmNdo25Faxwt15kh5c1bNfX5M3CjPP1/cudVbsFGtNTtjP3b/AMlNphkAAQAA'

describe('compression', () => {
    it('should compress and decompress a string consistently', () => {
        const compressed = compressToString('hello world')
        expect(compressed).toEqual('H4sIAAAAAAAAE8tgSGXIAcJ8BgWGciBZBGSnMAAA8G/J2xYAAAA=')

        const decompressed = decompressFromString(compressed)
        expect(decompressed).toEqual('hello world')
    })

    it('should decompress string from the python version', () => {
        const decompressed = decompressFromString(compressedData)
        expect(decompressed).toEqual(
            `[{"type": 3, "data": {"source": 1, "positions": [{"x": 679, "y": 790, "id": 3, "timeOffset": 0}]}, "timestamp": 1679569492338}]`
        )
    })
})
