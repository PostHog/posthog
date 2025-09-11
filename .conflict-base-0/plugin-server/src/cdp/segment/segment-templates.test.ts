import * as fs from 'fs'
import * as path from 'path'

import { SEGMENT_DESTINATIONS } from './segment-templates'

const testCases = SEGMENT_DESTINATIONS.filter((destination) => destination.template).map((destination) => ({
    id: destination.template?.id,
    destination,
}))

describe('segment templates', () => {
    test.each(testCases)('template $id matches expected result', ({ destination }) => {
        expect(destination.template).toMatchSnapshot()
    })

    test.each(testCases)('icon for template $id exists in frontend/public/services/', ({ destination }) => {
        const servicesDir = path.join(__dirname, '../../../.././frontend/public/services')

        if (!fs.existsSync(servicesDir)) {
            throw new Error(`Services directory not found: ${servicesDir}`)
        }

        const existingFiles = fs.readdirSync(servicesDir)
        const existingIcons = new Set(existingFiles.map((file) => file.toLowerCase()))

        const template = destination.template
        if (!template) {
            return
        }

        const iconUrl = template.icon_url

        if (!iconUrl || iconUrl === '/static/posthog-icon.svg') {
            return
        }

        const iconId = iconUrl.replace('/static/services/', '')

        const iconExists = existingIcons.has(`${iconId}`.toLowerCase())

        if (!iconExists) {
            throw new Error(`Missing icon: ${iconId} for template ${template.id}`)
        }
    })
})
