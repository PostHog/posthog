import { Message } from 'node-rdkafka'

const decodedValues = new WeakMap<Message, string>()

export function recordDecodedValue(message: Message, value: string): void {
    decodedValues.set(message, value)
}

export function takeDecodedMessageValue(message: Message): string | undefined {
    const decoded = decodedValues.get(message)
    if (decoded === undefined) {
        return message.value?.toString()
    }
    decodedValues.delete(message)
    return decoded
}
