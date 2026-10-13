const encoder = new TextEncoder()
const decoder = new TextDecoder()

export class NinePReader {
    private offset = 0
    private view: DataView

    constructor(private bytes: Uint8Array) {
        this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    }

    number(size: 1 | 2 | 4 | 8): number {
        const value =
            size === 8
                ? Number(this.view.getBigUint64(this.offset, true))
                : size === 4
                  ? this.view.getUint32(this.offset, true)
                  : size === 2
                    ? this.view.getUint16(this.offset, true)
                    : this.view.getUint8(this.offset)
        this.offset += size
        if (!Number.isSafeInteger(value)) {
            throw new Error('File offset is too large')
        }
        return value
    }

    data(size: number): Uint8Array {
        if (this.offset + size > this.bytes.length) {
            throw new Error('Truncated 9P message')
        }
        const result = this.bytes.slice(this.offset, this.offset + size)
        this.offset += size
        return result
    }

    string(): string {
        return decoder.decode(this.data(this.number(2)))
    }
}

export class NinePWriter {
    private bytes = new Uint8Array(256)
    private view = new DataView(this.bytes.buffer)
    private length = 0

    // Every 9P message crosses this writer, and a file read fills it one packet at a time.
    private reserve(size: number): void {
        if (this.length + size <= this.bytes.length) {
            return
        }
        let capacity = this.bytes.length * 2
        while (capacity < this.length + size) {
            capacity *= 2
        }
        const grown = new Uint8Array(capacity)
        grown.set(this.bytes.subarray(0, this.length))
        this.bytes = grown
        this.view = new DataView(grown.buffer)
    }

    number(value: number, size: 1 | 2 | 4 | 8): this {
        this.reserve(size)
        if (size === 8) {
            this.view.setBigUint64(this.length, BigInt(value), true)
        } else if (size === 4) {
            this.view.setUint32(this.length, value, true)
        } else if (size === 2) {
            this.view.setUint16(this.length, value, true)
        } else {
            this.view.setUint8(this.length, value)
        }
        this.length += size
        return this
    }

    data(value: Uint8Array): this {
        this.reserve(value.length)
        this.bytes.set(value, this.length)
        this.length += value.length
        return this
    }

    string(value: string): this {
        const bytes = encoder.encode(value)
        return this.number(bytes.length, 2).data(bytes)
    }

    build(): Uint8Array {
        return this.bytes.slice(0, this.length)
    }

    frame(type: number, tag: number): Uint8Array {
        const frame = new Uint8Array(this.length + 7)
        const view = new DataView(frame.buffer)
        view.setUint32(0, frame.length, true)
        view.setUint8(4, type)
        view.setUint16(5, tag, true)
        frame.set(this.bytes.subarray(0, this.length), 7)
        return frame
    }
}
