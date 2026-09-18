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
    private bytes: number[] = []

    number(value: number, size: 1 | 2 | 4 | 8): this {
        let remaining = BigInt(value)
        for (let i = 0; i < size; i++) {
            this.bytes.push(Number(remaining & 255n))
            remaining >>= 8n
        }
        return this
    }

    data(value: Uint8Array): this {
        for (const byte of value) {
            this.bytes.push(byte)
        }
        return this
    }

    string(value: string): this {
        const bytes = encoder.encode(value)
        return this.number(bytes.length, 2).data(bytes)
    }

    build(): Uint8Array {
        return Uint8Array.from(this.bytes)
    }

    frame(type: number, tag: number): Uint8Array {
        return new NinePWriter()
            .number(this.bytes.length + 7, 4)
            .number(type, 1)
            .number(tag, 2)
            .data(this.build())
            .build()
    }
}
