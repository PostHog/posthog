import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'

import { SEGMENT_DESTINATIONS } from './segment-templates'

// Script to store the segment icons in the static folder
const logoDevPublishableKey = process.env.LOGO_DEV_PUBLISHABLE_KEY ?? process.env.LOGO_DEV_TOKEN

if (!logoDevPublishableKey?.startsWith('pk_')) {
    throw new Error('Set LOGO_DEV_PUBLISHABLE_KEY to a logo.dev publishable key')
}

void SEGMENT_DESTINATIONS.map(async ({ template }) => {
    const iconId = template.icon_url?.replace('/static/services/', '')

    // eslint-disable-next-line no-restricted-globals
    const res = await fetch(`https://img.logo.dev/${iconId}?token=${logoDevPublishableKey}`)
    if (!res.ok || !res.headers.get('content-type')?.startsWith('image/')) {
        throw new Error(`logo.dev returned an invalid image response for ${iconId} (${res.status})`)
    }
    const buffer = await res.arrayBuffer()

    // Ensure directory exists
    const servicesDir = join(process.cwd(), '..', 'frontend', 'public', 'services')
    mkdirSync(servicesDir, { recursive: true })

    // Save image with iconId as filename and .png extension
    const filePath = join(servicesDir, `${iconId}.png`)
    writeFileSync(filePath, new Uint8Array(buffer))
    console.log(`Saved ${iconId}.png to ${filePath}`)
})
