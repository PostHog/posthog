import { Plugin, PluginEvent, RetryError } from '@posthog/plugin-scaffold'
import { Storage, Bucket } from '@google-cloud/storage'
import { PassThrough } from 'stream'
import { randomBytes } from 'crypto'


type GCSPlugin = Plugin<{
    global: {
        bucket: Bucket
        eventsToIgnore: Set<string>
    }
    config: {
        bucketName: string
        exportEventsToIgnore: string
    }
    jobs: {
        exportEventsWithRetry: string[]
    }
}>

interface GCSCredentials {
    project_id?: string
    client_email?: string
    private_key?: string
}

interface TableRow {
    uuid: string
    event: string
    properties: string // Record<string, any>
    elements: string // Record<string, any>
    people_set: string // Record<string, any>
    people_set_once: string // Record<string, any>
    distinct_id: string
    team_id: number
    ip: string
    site_url: string
    timestamp: string
}

function transformEventToRow(fullEvent: PluginEvent): TableRow {
    const { event, properties, $set, $set_once, distinct_id, team_id, site_url, now, sent_at, uuid, ...rest } =
        fullEvent
    const ip = properties?.['$ip'] || fullEvent.ip
    const timestamp = fullEvent.timestamp || properties?.timestamp || now || sent_at
    let ingestedProperties = properties
    let elements = []

    // only move prop to elements for the $autocapture action
    if (event === '$autocapture' && properties?.['$elements']) {
        const { $elements, ...props } = properties
        ingestedProperties = props
        elements = $elements
    }

    return {
        event,
        distinct_id,
        team_id,
        ip,
        site_url,
        timestamp,
        uuid: uuid!,
        properties: JSON.stringify(ingestedProperties || {}),
        elements: JSON.stringify(elements || []),
        people_set: JSON.stringify($set || {}),
        people_set_once: JSON.stringify($set_once || {}),
    }
}

export const setupPlugin: GCSPlugin['setupPlugin'] = async ({ attachments, global, config }) => {
    if (!attachments.googleCloudKeyJson) {
        throw new Error('Credentials JSON file not provided!')
    }
    if (!config.bucketName) {
        throw new Error('Table Name not provided!')
    }

    let credentials: GCSCredentials
    try {
        credentials = JSON.parse(attachments.googleCloudKeyJson.contents.toString())
    } catch {
        throw new Error('Credentials JSON file has invalid JSON!')
    }

    const storage = new Storage({
        projectId: credentials['project_id'],
        credentials,
        autoRetry: false,
    })
    global.bucket = storage.bucket(config.bucketName)
    global.eventsToIgnore = new Set<string>((config.exportEventsToIgnore || '').split(',').map((event) => event.trim()))
}

export const onEvent: GCSPlugin['onEvent'] = async (event, { global, config }) => {
    if (global.eventsToIgnore.has(event.event.trim())) {
        return
    }
    const rows = [transformEventToRow(event)]

    let csvString =
        'uuid,event,properties,elements,people_set,people_set_once,distinct_id,team_id,ip,site_url,timestamp\n'

    for (let i = 0; i < rows.length; ++i) {
        const {
            uuid,
            event,
            properties,
            elements,
            people_set,
            people_set_once,
            distinct_id,
            team_id,
            ip,
            site_url,
            timestamp,
        } = rows[i]

        // order is important
        csvString += `${uuid},${event},${properties},${elements},${people_set},${people_set_once},${distinct_id},${team_id},${ip},${site_url},${timestamp}`

        if (i !== rows.length - 1) {
            csvString += '\n'
        }
    }

    const date = new Date().toISOString()
    const [day, time] = date.split('T')
    const dayTime = `${day.split('-').join('')}-${time.split(':').join('')}`
    const suffix = randomBytes(8).toString('hex')

    const fileName = `${day}/${dayTime}-${suffix}.csv`

    // some minor hackiness to upload without access to the filesystem
    const dataStream = new PassThrough()
    const gcFile = global.bucket.file(fileName)

    dataStream.push(csvString)
    dataStream.push(null)
    try {
        await new Promise((resolve, reject) => {
            dataStream
                .pipe(
                    gcFile.createWriteStream({
                        resumable: false,
                        validation: false,
                    })
                )
                .on('error', (error: Error) => {
                    reject(error)
                })
                .on('finish', () => {
                    resolve(true)
                })
        })
    } catch {
        console.error(`Failed to upload ${rows.length} event${rows.length > 1 ? 's' : ''} to GCS. Retrying later.`)
        throw new RetryError()
    }

}
