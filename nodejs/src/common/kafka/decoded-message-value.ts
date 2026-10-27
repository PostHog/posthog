import { Message } from 'node-rdkafka'

const decodedValues = new WeakMap<Message, string>()

export function recordDecodedValue(message: Message, value: string): void {
    decodedValues.set(message, value)
}

export function decodedMessageValue(message: Message): string | undefined {
    return decodedValues.get(message) ?? message.value?.toString()
}
