import type { EvaluationReportDeliveryTarget } from '../types'

/** Where a report goes, in words: "Sent to #alerts and 2 email addresses", or "Shown only here". */
export function reportDestinationsText(targets: EvaluationReportDeliveryTarget[]): string {
    const parts: string[] = []
    for (const target of targets) {
        if (target.type === 'slack' && target.channel) {
            // A Slack target stores "channel id|channel name".
            const name = target.channel.split('|')[1] || target.channel
            parts.push(name.startsWith('#') ? name : `#${name}`)
        }
        if (target.type === 'email' && target.value) {
            const count = target.value.split(',').filter((address) => address.trim()).length
            parts.push(count === 1 ? '1 email address' : `${count} email addresses`)
        }
    }
    return parts.length > 0 ? `Sent to ${parts.join(' and ')}` : 'Shown only here'
}
