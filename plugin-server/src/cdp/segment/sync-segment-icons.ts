import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'

import { SEGMENT_DESTINATIONS } from './segment-templates'

// Script to store the segment icons in the static folder

void SEGMENT_DESTINATIONS.splice(0, 2).map(async ({ template }) => {
    const iconId = template.icon_url?.replace('/static/services/', '')

    const res = await fetch(`https://img.logo.dev/${iconId}?token=abc`)
    const buffer = await res.arrayBuffer()

    // Ensure directory exists
    const servicesDir = join(process.cwd(), '..', 'frontend', 'public', 'services')
    mkdirSync(servicesDir, { recursive: true })

    // Save image with iconId as filename and .png extension
    const filePath = join(servicesDir, `${iconId}.png`)
    writeFileSync(filePath, new Uint8Array(buffer))
    console.log(`Saved ${iconId}.png to ${filePath}`)
})
