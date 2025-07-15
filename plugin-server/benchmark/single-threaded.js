#!/usr/bin/env node
import { createReadStream } from 'fs'
import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

import { Serializer } from './serializer.js'

const argv = yargs(hideBin(process.argv))
    .option('file', {
        alias: 'f',
        type: 'string',
        description: 'Path to file',
        demandOption: true,
    })
    .option('loops', {
        alias: 'l',
        type: 'number',
        description: 'Number of times to process the file',
        default: 1,
    })
    .option('format', {
        alias: 'fmt',
        type: 'string',
        description: 'Input format: json or protobuf',
        default: 'json',
        choices: ['json', 'protobuf'],
    })
    .help().argv

const FILE_PATH = argv.file
const LOOPS = argv.loops
const FORMAT = argv.format

let messageCount = 0
const startTime = Date.now()
let lastReportTime = startTime
let currentLoop = 0

const serializer = new Serializer(FORMAT)

function reportProgress() {
    const now = Date.now()
    const elapsed = (now - startTime) / 1000
    const rate = messageCount / elapsed
    const timeSinceLastReport = (now - lastReportTime) / 1000
    const recentRate = messageCount / timeSinceLastReport

    console.error(
        `Processed ${messageCount} messages in ${elapsed.toFixed(1)}s (${rate.toFixed(
            0
        )} msg/s, recent: ${recentRate.toFixed(0)} msg/s, loop: ${currentLoop}/${LOOPS}, format: ${FORMAT})`
    )

    lastReportTime = now
    messageCount = 0
}

// Set up progress reporting every 5 seconds
const progressInterval = setInterval(reportProgress, 5000)

function processFile() {
    return new Promise((resolve) => {
        const stream = createReadStream(FILE_PATH)
        let buffer = Buffer.alloc(0)

        stream.on('data', async (chunk) => {
            buffer = Buffer.concat([buffer, chunk])

            while (buffer.length >= 4) {
                const messageLength = buffer.readUInt32BE(0)

                if (buffer.length >= 4 + messageLength) {
                    const messageData = buffer.slice(4, 4 + messageLength)
                    buffer = buffer.slice(4 + messageLength)

                    try {
                        await serializer.deserialize(messageData)
                        messageCount++
                    } catch (error) {
                        console.error(`Failed to parse message: ${error}`)
                    }
                } else {
                    break
                }
            }
        })

        stream.on('close', () => {
            resolve()
        })
    })
}

async function runLoops() {
    for (let i = 0; i < LOOPS; i++) {
        currentLoop = i + 1
        console.error(`Starting loop ${currentLoop}/${LOOPS}`)
        await processFile()
    }

    clearInterval(progressInterval)
    const totalTime = (Date.now() - startTime) / 1000
    console.error(`\nFinished processing ${LOOPS} loops. Total time: ${totalTime.toFixed(1)}s`)
}

void runLoops()
