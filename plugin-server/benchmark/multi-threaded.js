#!/usr/bin/env node
import { createReadStream } from 'fs'
import { Worker } from 'worker_threads'
import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

const argv = yargs(hideBin(process.argv))
    .option('file', {
        alias: 'f',
        type: 'string',
        description: 'Path to file',
        demandOption: true,
    })
    .option('workers', {
        alias: 'w',
        type: 'number',
        description: 'Number of worker threads',
        default: 4,
    })
    .option('batch-size', {
        alias: 'b',
        type: 'number',
        description: 'Number of messages to batch together',
        default: 100,
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
const NUM_WORKERS = argv.workers
const BATCH_SIZE = argv['batch-size']
const LOOPS = argv.loops
const FORMAT = argv.format

// Main thread logic
let messageCount = 0
const startTime = Date.now()
let lastReportTime = startTime
let activeWorkers = 0
let totalSent = 0
let currentLoop = 0

// Create worker pool
const workers = []
const availableWorkers = []

for (let i = 0; i < NUM_WORKERS; i++) {
    const worker = new Worker(new URL('./worker.js', import.meta.url), {
        workerData: { workerId: i, format: FORMAT },
    })

    worker.on('message', (message) => {
        if (message.type === 'completed') {
            messageCount += message.count
            availableWorkers.push(worker)
            activeWorkers--

            // Check if we can resume reading or send more work
            if (paused) {
                paused = false
                resumeReading()
            }
        }
    })

    worker.on('error', (error) => {
        console.error(`Worker error: ${error}`)
    })

    workers.push(worker)
    availableWorkers.push(worker)
}

function reportProgress() {
    const now = Date.now()
    const elapsed = (now - startTime) / 1000
    const rate = messageCount / elapsed
    const timeSinceLastReport = (now - lastReportTime) / 1000
    const recentRate = messageCount / timeSinceLastReport

    console.error(
        `Processed ${messageCount} messages in ${elapsed.toFixed(1)}s (${rate.toFixed(
            0
        )} msg/s, recent: ${recentRate.toFixed(
            0
        )} msg/s, active workers: ${activeWorkers}/${NUM_WORKERS}, total sent: ${totalSent}, loop: ${currentLoop}/${LOOPS}, format: ${FORMAT})`
    )

    lastReportTime = now
    messageCount = 0
}

// Set up progress reporting every 5 seconds
const progressInterval = setInterval(reportProgress, 5000)

let paused = false
let currentBatch = []
let stream = null
let buffer = Buffer.alloc(0)

function resumeReading() {
    if (paused && availableWorkers.length > 0) {
        paused = false
        processNextMessages()
    }
}

function processNextMessages() {
    while (buffer.length >= 4 && availableWorkers.length > 0) {
        const messageLength = buffer.readUInt32BE(0)

        if (buffer.length >= 4 + messageLength) {
            const messageData = buffer.slice(4, 4 + messageLength)
            buffer = buffer.slice(4 + messageLength)

            currentBatch.push(messageData)

            if (currentBatch.length >= BATCH_SIZE) {
                const worker = availableWorkers.pop()
                worker.postMessage({ type: 'parse', data: currentBatch })
                activeWorkers++
                totalSent += currentBatch.length
                currentBatch = []
            }
        } else {
            break
        }
    }

    if (availableWorkers.length === 0) {
        paused = true
    }
}

function processFile() {
    return new Promise((resolve) => {
        stream = createReadStream(FILE_PATH)

        stream.on('data', (chunk) => {
            buffer = Buffer.concat([buffer, chunk])
            processNextMessages()
        })

        stream.on('close', () => {
            // Send remaining batch if any
            if (currentBatch.length > 0 && availableWorkers.length > 0) {
                const worker = availableWorkers.pop()
                worker.postMessage({ type: 'parse', data: currentBatch })
                activeWorkers++
                totalSent += currentBatch.length
            }
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

    // Wait for all workers to finish
    const waitForCompletion = () => {
        if (activeWorkers > 0) {
            setTimeout(waitForCompletion, 100)
        } else {
            clearInterval(progressInterval)
            const totalTime = (Date.now() - startTime) / 1000
            console.error(
                `\nFinished processing ${LOOPS} loops. Total time: ${totalTime.toFixed(1)}s, total sent: ${totalSent}`
            )

            // Terminate workers
            workers.forEach((worker) => worker.terminate())
        }
    }
    waitForCompletion()
}

void runLoops()
