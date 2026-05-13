import { NativeTemplate } from '~/cdp/types'

const DISCORD_WEBHOOK_PATTERN = /^https:\/\/discord\.com\/api\/webhooks\/.+/

const STATUS_EMOJI: Record<string, string> = {
    up: '🟢',
    down: '🔴',
    unknown: '⚪',
}

function buildContent(properties: Record<string, any>): string {
    const name = properties.monitor_name || 'Monitor'
    const url = properties.monitor_url || ''
    const next = String(properties.new_status || 'unknown')
    const emoji = STATUS_EMOJI[next] ?? STATUS_EMOJI.unknown

    return `${emoji} **${name}** is now **${next.toUpperCase()}**\n${url}`
}

export const template: NativeTemplate = {
    free: true,
    status: 'stable',
    type: 'destination',
    id: 'native-discord-uptime',
    name: 'Discord (Uptime)',
    description: 'Sends a Discord message when an uptime monitor changes status',
    icon_url: '/static/services/discord.png',
    category: ['Uptime'],
    perform: (request, { payload, globals }) => {
        if (!payload.webhookUrl || !DISCORD_WEBHOOK_PATTERN.test(String(payload.webhookUrl))) {
            throw new Error('Invalid Discord webhook URL. Expected https://discord.com/api/webhooks/...')
        }

        const properties = globals?.event?.properties ?? {}

        return request(String(payload.webhookUrl), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            json: { content: buildContent(properties) },
        })
    },
    inputs_schema: [
        {
            key: 'webhookUrl',
            type: 'string',
            label: 'Webhook URL',
            description:
                'See https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks for how to generate one.',
            secret: true,
            required: true,
        },
    ],
}
