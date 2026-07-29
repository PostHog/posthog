import { HogFunctionType } from '~/types'

export function getNotificationDescription(fn: Pick<HogFunctionType, 'inputs'>): string | null {
    const inputs = fn.inputs
    if (!inputs) {
        return null
    }
    const destinationUrl = inputs.url?.value || inputs.webhookUrl?.value
    if (destinationUrl) {
        try {
            return new URL(String(destinationUrl)).hostname
        } catch {
            return String(destinationUrl)
        }
    }
    if (inputs.channel?.value) {
        return String(inputs.channel.value)
    }
    if (inputs.email?.value) {
        return String(inputs.email.value)
    }
    return null
}
