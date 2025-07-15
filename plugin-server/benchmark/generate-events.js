#!/usr/bin/env node
import { randomUUID } from 'crypto'
import { writeFileSync } from 'fs'
import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

import { Serializer } from './serializer.js'

const argv = yargs(hideBin(process.argv))
    .option('num-events', {
        alias: 'n',
        type: 'number',
        description: 'Number of events to generate',
        demandOption: true,
    })
    .option('event-size', {
        alias: 's',
        type: 'number',
        description: 'Approximate size of the properties object in bytes',
        default: 256,
    })
    .option('subsequent-events', {
        alias: 'k',
        type: 'number',
        description: 'Number of subsequent events per distinct id',
        default: 1,
    })
    .option('format', {
        alias: 'f',
        type: 'string',
        description: 'Output format: json or protobuf',
        default: 'json',
        choices: ['json', 'protobuf'],
    })
    .option('output', {
        alias: 'o',
        type: 'string',
        description: 'Output file path',
        demandOption: true,
    })
    .help().argv

const NUM_EVENTS = argv['num-events']
const EVENT_SIZE = argv['event-size']
const SUBSEQUENT_EVENTS = argv['subsequent-events']
const FORMAT = argv.format
const OUTPUT_FILE = argv.output

const TEAM_ID = 1
const EVENT_NAME = 'benchmark_event'
const now = Date.now()

const serializer = new Serializer(FORMAT)

function randomString(length) {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    let result = ''
    for (let i = 0; i < length; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length))
    }
    return result
}

function generateProperties(size) {
    // Generate a properties object with random keys/values to reach the target size
    const props = {}
    let currentSize = 2 // {}
    let i = 0
    while (currentSize < size) {
        const key = 'k' + randomString(6)
        const value = randomString(12)
        props[key] = value
        currentSize = Buffer.byteLength(JSON.stringify(props))
        i++
        if (i > 10000) {
            break
        } // safety
    }
    return props
}

const numDistinctIds = Math.ceil(NUM_EVENTS / SUBSEQUENT_EVENTS)
const distinctIds = Array.from({ length: numDistinctIds }, () => randomString(12))

async function generateEvents() {
    const chunks = []

    for (let i = 0; i < NUM_EVENTS; ++i) {
        const distinctId = distinctIds[Math.floor(i / SUBSEQUENT_EVENTS)]
        const event = {
            uuid: randomUUID(),
            event: EVENT_NAME,
            properties: generateProperties(EVENT_SIZE),
            timestamp: new Date(now + i * 1000).toISOString(),
            team_id: TEAM_ID,
            distinct_id: distinctId,
            elements_chain: '',
            created_at: new Date(now + i * 1000).toISOString(),
            person_id: randomUUID(),
            person_created_at: new Date(now + i * 1000).toISOString(),
            person_properties: '{}',
            group0_properties: '{}',
            group1_properties: '{}',
            group2_properties: '{}',
            group3_properties: '{}',
            group4_properties: '{}',
            group0_created_at: new Date(now + i * 1000).toISOString(),
            group1_created_at: new Date(now + i * 1000).toISOString(),
            group2_created_at: new Date(now + i * 1000).toISOString(),
            group3_created_at: new Date(now + i * 1000).toISOString(),
            group4_created_at: new Date(now + i * 1000).toISOString(),
            person_mode: 'full',
        }

        const serialized = await serializer.serialize(event)
        const serializedBuffer = Buffer.from(serialized)
        const lengthBuffer = Buffer.alloc(4)
        lengthBuffer.writeUInt32BE(serializedBuffer.length, 0)

        chunks.push(lengthBuffer)
        chunks.push(serializedBuffer)

        if ((i + 1) % 10000 === 0 || i === NUM_EVENTS - 1) {
            process.stderr.write(`Generated ${i + 1} events in ${FORMAT} format\n`)
        }
    }

    const finalBuffer = Buffer.concat(chunks)
    writeFileSync(OUTPUT_FILE, finalBuffer)
    process.stderr.write(`Written ${NUM_EVENTS} events to ${OUTPUT_FILE}\n`)
}

void generateEvents()
