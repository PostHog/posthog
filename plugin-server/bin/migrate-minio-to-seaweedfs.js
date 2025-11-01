#!/usr/bin/env node

/**
 * Migration script to copy session recording data from MinIO to SeaweedFS
 *
 * This script safely migrates session recording objects from MinIO (port 19000)
 * to SeaweedFS (port 8333) for local development environments only.
 *
 * Usage:
 *   node bin/migrate-minio-to-seaweedfs.js [options]
 *
 * Options:
 *   --service <name>    Service to migrate (default: session-recordings)
 *   --force             Overwrite existing objects in destination
 *   --dry-run           Show what would be migrated without copying
 *   --workers <n>       Number of concurrent workers (default: 5)
 *   --resume            Resume from last checkpoint
 *   --revert            Copy from SeaweedFS back to MinIO (reverse direction)
 *   --help              Show this help message
 */

const {
    S3Client,
    ListObjectsV2Command,
    GetObjectCommand,
    PutObjectCommand,
    HeadObjectCommand,
    CreateBucketCommand,
} = require('@aws-sdk/client-s3')
const { existsSync, readFileSync, writeFileSync } = require('fs')

// Service configurations
const SERVICES = {
    'session-recordings': {
        bucket: 'posthog',
        prefix: 'session_recordings/',
        description: 'Session recording blobs',
    },
}

// Checkpoint file for resumable migrations
const CHECKPOINT_FILE = '.migration-checkpoint.json'

class Checkpoint {
    constructor(serviceName) {
        this.serviceName = serviceName
        this.data = this.load()
    }

    load() {
        if (existsSync(CHECKPOINT_FILE)) {
            try {
                return JSON.parse(readFileSync(CHECKPOINT_FILE, 'utf-8'))
            } catch (err) {
                console.warn('⚠️  Failed to load checkpoint, starting fresh')
                return {}
            }
        }
        return {}
    }

    save() {
        writeFileSync(CHECKPOINT_FILE, JSON.stringify(this.data, null, 2))
    }

    getServiceData(serviceName) {
        if (!this.data[serviceName]) {
            this.data[serviceName] = {
                completed: [],
                failed: {},
                lastKey: null,
                startTime: Date.now(),
            }
        }
        return this.data[serviceName]
    }

    markCompleted(serviceName, key) {
        const data = this.getServiceData(serviceName)
        data.completed.push(key)
        data.lastKey = key
    }

    markFailed(serviceName, key, error) {
        const data = this.getServiceData(serviceName)
        data.failed[key] = error.message || String(error)
    }

    markSkipped(serviceName) {
        const data = this.getServiceData(serviceName)
        data.skipped = (data.skipped || 0) + 1
    }

    isCompleted(serviceName, key) {
        const data = this.getServiceData(serviceName)
        return data.completed.includes(key)
    }

    getLastKey(serviceName) {
        const data = this.getServiceData(serviceName)
        return data.lastKey
    }
}

class ProgressTracker {
    constructor(total) {
        this.total = total
        this.completed = 0
        this.failed = 0
        this.skipped = 0
        this.bytesTransferred = 0
        this.startTime = Date.now()
    }

    increment(type, bytes = 0) {
        this[type]++
        if (bytes > 0) {
            this.bytesTransferred += bytes
        }
        this.print()
    }

    print() {
        const processed = this.completed + this.failed + this.skipped
        const percent = Math.round((processed / this.total) * 100)
        const elapsed = (Date.now() - this.startTime) / 1000
        const rate = elapsed > 0 ? processed / elapsed : 0
        const remaining = rate > 0 ? (this.total - processed) / rate : 0
        const mbTransferred = (this.bytesTransferred / 1024 / 1024).toFixed(2)
        const mbPerSec = elapsed > 0 ? (this.bytesTransferred / 1024 / 1024 / elapsed).toFixed(2) : '0.00'

        const barLength = 30
        const filledLength = Math.floor((percent / 100) * barLength)
        const bar = '█'.repeat(filledLength) + '░'.repeat(barLength - filledLength)

        process.stdout.write(
            `\r[${bar}] ${percent}% | ${processed}/${this.total} objects | ` +
                `⏱ ${Math.floor(elapsed)}s | Est. ${Math.floor(remaining)}s remaining | ` +
                `📊 ${mbTransferred} MB (${mbPerSec} MB/s) | ✓ ${this.completed} | ✗ ${this.failed} | ⊘ ${this.skipped}`
        )
    }

    finish() {
        process.stdout.write('\n')
    }
}

function parseArgs() {
    const args = process.argv.slice(2)
    const options = {
        service: 'session-recordings',
        force: false,
        dryRun: false,
        workers: 5,
        resume: false,
        revert: false,
    }

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--service':
                options.service = args[++i]
                break
            case '--force':
                options.force = true
                break
            case '--dry-run':
                options.dryRun = true
                break
            case '--workers':
                options.workers = parseInt(args[++i], 10)
                break
            case '--resume':
                options.resume = true
                break
            case '--revert':
                options.revert = true
                break
            case '--help':
                console.log(__doc__)
                process.exit(0)
            default:
                console.error(`Unknown option: ${args[i]}`)
                process.exit(1)
        }
    }

    return options
}

function ensureLocalDevelopmentOnly(minioEndpoint, seaweedfsEndpoint) {
    // Check endpoints are localhost
    const localPatterns = [/^https?:\/\/(localhost|127\.0\.0\.1|::1)(:\d+)?/, /^https?:\/\/[^.]+:\d+$/]

    const isMinioLocal = localPatterns.some((p) => p.test(minioEndpoint))
    const isSeaweedFSLocal = localPatterns.some((p) => p.test(seaweedfsEndpoint))

    if (!isMinioLocal || !isSeaweedFSLocal) {
        console.error('❌ SAFETY CHECK FAILED: Non-local endpoint detected')
        console.error(`   MinIO endpoint: ${minioEndpoint}`)
        console.error(`   SeaweedFS endpoint: ${seaweedfsEndpoint}`)
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        process.exit(1)
    }

    // Check NODE_ENV or DEBUG
    const nodeEnv = process.env.NODE_ENV?.toLowerCase()
    const isDebug = ['y', 'yes', 't', 'true', 'on', '1'].includes(String(process.env.DEBUG).toLowerCase())

    let isDev = false
    if (nodeEnv) {
        isDev = nodeEnv.startsWith('dev') || nodeEnv.startsWith('test')
    } else if (isDebug) {
        isDev = true
    }

    if (!isDev) {
        console.error('❌ SAFETY CHECK FAILED: Not running in development environment')
        console.error(`   NODE_ENV: ${process.env.NODE_ENV || 'not set'}`)
        console.error(`   DEBUG: ${process.env.DEBUG || 'not set'}`)
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        console.error('   Set NODE_ENV=development or DEBUG=1 to run.')
        process.exit(1)
    }

    // Check for AWS production indicators
    const awsIndicators = ['AWS_EXECUTION_ENV', 'AWS_LAMBDA_FUNCTION_NAME', 'ECS_CONTAINER_METADATA_URI']
    const foundIndicators = awsIndicators.filter((key) => process.env[key])

    if (foundIndicators.length > 0) {
        console.error('❌ SAFETY CHECK FAILED: AWS production environment detected')
        console.error(`   Found: ${foundIndicators.join(', ')}`)
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        process.exit(1)
    }

    console.log('✅ Safety checks passed: Local development environment confirmed')
}

async function createS3Client(endpoint, accessKeyId, secretAccessKey) {
    return new S3Client({
        endpoint,
        region: 'us-east-1',
        credentials: {
            accessKeyId,
            secretAccessKey,
        },
        forcePathStyle: true,
    })
}

async function ensureBucketExists(client, bucket) {
    try {
        // Try to list objects to check if bucket exists
        await client.send(new ListObjectsV2Command({ Bucket: bucket, MaxKeys: 1 }))
        console.log(`✅ Bucket '${bucket}' exists`)
    } catch (err) {
        if (err.name === 'NoSuchBucket' || err.name === 'NotFound' || err.$metadata?.httpStatusCode === 404) {
            console.log(`📦 Creating bucket '${bucket}'...`)
            try {
                await client.send(new CreateBucketCommand({ Bucket: bucket }))
                console.log(`✅ Bucket '${bucket}' created`)
            } catch (createErr) {
                // Ignore error if bucket already exists (race condition)
                if (createErr.name === 'BucketAlreadyOwnedByYou' || createErr.name === 'BucketAlreadyExists') {
                    console.log(`✅ Bucket '${bucket}' already exists`)
                } else {
                    console.error(`❌ Failed to create bucket '${bucket}':`, createErr.message)
                    throw createErr
                }
            }
        } else {
            // Ignore other errors (bucket might exist)
            console.log(`✅ Assuming bucket '${bucket}' exists`)
        }
    }
}

async function testConnectivity(client, endpoint, bucket) {
    try {
        const command = new ListObjectsV2Command({ Bucket: bucket, MaxKeys: 1 })
        await client.send(command)
        console.log(`✅ Connected to ${endpoint}`)
        return true
    } catch (err) {
        console.error(`❌ Cannot connect to ${endpoint} bucket '${bucket}': ${err.message}`)
        return false
    }
}

async function objectExists(client, bucket, key) {
    try {
        await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }))
        return true
    } catch (err) {
        if (err.name === 'NotFound' || err.$metadata?.httpStatusCode === 404) {
            return false
        }
        throw err
    }
}

async function copyObject(sourceClient, destClient, bucket, key) {
    const getCommand = new GetObjectCommand({ Bucket: bucket, Key: key })
    const response = await sourceClient.send(getCommand)

    const chunks = []
    for await (const chunk of response.Body) {
        chunks.push(chunk)
    }
    const buffer = Buffer.concat(chunks)

    const putCommand = new PutObjectCommand({
        Bucket: bucket,
        Key: key,
        Body: buffer,
        ContentType: response.ContentType || 'application/octet-stream',
    })
    await destClient.send(putCommand)

    return { size: buffer.length }
}

async function migrateService(serviceName, config, options, checkpoint) {
    const direction = options.revert ? 'SeaweedFS → MinIO' : 'MinIO → SeaweedFS'
    const sourceName = options.revert ? 'SeaweedFS' : 'MinIO'
    const destName = options.revert ? 'MinIO' : 'SeaweedFS'

    console.log(`\n${'='.repeat(80)}`)
    console.log(`📦 Migrating: ${serviceName}`)
    console.log(`   ${config.description}`)
    console.log(`   Direction: ${direction}`)
    console.log(`   Bucket: ${config.bucket}`)
    console.log(`   Prefix: ${config.prefix}`)
    console.log(`${'='.repeat(80)}\n`)

    // Create S3 clients
    const minioClient = await createS3Client(
        'http://localhost:19000',
        'object_storage_root_user',
        'object_storage_root_password'
    )
    const seaweedfsClient = await createS3Client('http://localhost:8333', 'any', 'any')

    // Determine source and destination based on direction
    const sourceClient = options.revert ? seaweedfsClient : minioClient
    const destClient = options.revert ? minioClient : seaweedfsClient

    // Ensure bucket exists in destination
    await ensureBucketExists(destClient, config.bucket)

    // Test connectivity
    const minioOk = await testConnectivity(minioClient, 'MinIO', config.bucket)
    const seaweedfsOk = await testConnectivity(seaweedfsClient, 'SeaweedFS', config.bucket)

    if (!minioOk || !seaweedfsOk) {
        throw new Error('Failed to connect to storage backends')
    }

    // List objects from source
    console.log(`📋 Listing objects from ${sourceName}...`)
    let allObjects = []
    let continuationToken = undefined

    do {
        const command = new ListObjectsV2Command({
            Bucket: config.bucket,
            Prefix: config.prefix,
            ContinuationToken: continuationToken,
        })
        const response = await sourceClient.send(command)

        if (response.Contents) {
            allObjects = allObjects.concat(response.Contents)
        }

        continuationToken = response.NextContinuationToken
    } while (continuationToken)

    console.log(`✅ Found ${allObjects.length} objects`)

    if (allObjects.length === 0) {
        console.log('✨ No objects to migrate')
        return
    }

    // Filter objects based on checkpoint and resume
    let objectsToProcess = allObjects
    if (options.resume) {
        const lastKey = checkpoint.getLastKey(serviceName)
        if (lastKey) {
            const lastIndex = allObjects.findIndex((obj) => obj.Key === lastKey)
            if (lastIndex >= 0) {
                objectsToProcess = allObjects.slice(lastIndex + 1)
                console.log(`📍 Resuming from key: ${lastKey}`)
                console.log(`   ${objectsToProcess.length} objects remaining`)
            }
        }
    }

    if (options.dryRun) {
        console.log('\n🔍 DRY RUN MODE - No objects will be copied\n')
        console.log('Objects that would be migrated:')
        objectsToProcess.slice(0, 10).forEach((obj) => {
            console.log(`  - ${obj.Key} (${(obj.Size / 1024).toFixed(2)} KB)`)
        })
        if (objectsToProcess.length > 10) {
            console.log(`  ... and ${objectsToProcess.length - 10} more`)
        }
        return
    }

    // Copy objects with progress tracking
    console.log(`\n🚀 Starting migration with ${options.workers} workers...\n`)
    const progress = new ProgressTracker(objectsToProcess.length)
    const failedObjects = []

    // Worker pool
    const workers = []
    const queue = [...objectsToProcess]

    for (let i = 0; i < options.workers; i++) {
        workers.push(
            (async () => {
                while (true) {
                    const obj = queue.shift()
                    if (!obj) break

                    try {
                        const exists = await objectExists(destClient, config.bucket, obj.Key)
                        if (exists && !options.force) {
                            checkpoint.markSkipped(serviceName)
                            progress.increment('skipped')
                        } else {
                            const result = await copyObject(sourceClient, destClient, config.bucket, obj.Key)
                            checkpoint.markCompleted(serviceName, obj.Key)
                            progress.increment('completed', result.size)
                        }
                    } catch (err) {
                        checkpoint.markFailed(serviceName, obj.Key, err)
                        progress.increment('failed')
                        failedObjects.push({ key: obj.Key, error: err.message })
                    }

                    // Save checkpoint every 100 objects
                    if ((progress.completed + progress.failed + progress.skipped) % 100 === 0) {
                        checkpoint.save()
                    }
                }
            })()
        )
    }

    await Promise.all(workers)
    progress.finish()

    // Final checkpoint save
    checkpoint.save()

    // Summary
    console.log(`\n${'='.repeat(80)}`)
    console.log('📊 Migration Summary')
    console.log(`${'='.repeat(80)}`)
    console.log(`✅ Completed: ${progress.completed}`)
    console.log(`⊘  Skipped:   ${progress.skipped}`)
    console.log(`✗  Failed:    ${progress.failed}`)
    console.log(`📦 Data transferred: ${(progress.bytesTransferred / 1024 / 1024).toFixed(2)} MB`)
    console.log(`⏱  Total time: ${Math.floor((Date.now() - progress.startTime) / 1000)}s`)

    if (failedObjects.length > 0) {
        console.log(`\n❌ Failed objects:`)
        failedObjects.slice(0, 10).forEach((obj) => {
            console.log(`   ${obj.key}: ${obj.error}`)
        })
        if (failedObjects.length > 10) {
            console.log(`   ... and ${failedObjects.length - 10} more`)
        }
        console.log(`\n💡 Run with --resume to retry failed objects`)
    }
}

async function main() {
    const options = parseArgs()

    const title = options.revert ? 'SeaweedFS to MinIO Migration Tool' : 'MinIO to SeaweedFS Migration Tool'
    console.log(`🔄 ${title}`)
    console.log('=====================================\n')

    // Validate service
    const config = SERVICES[options.service]
    if (!config) {
        console.error(`❌ Unknown service: ${options.service}`)
        console.error(`Available services: ${Object.keys(SERVICES).join(', ')}`)
        process.exit(1)
    }

    // Safety checks
    ensureLocalDevelopmentOnly('http://localhost:19000', 'http://localhost:8333')

    // Initialize checkpoint
    const checkpoint = new Checkpoint(options.service)

    try {
        await migrateService(options.service, config, options, checkpoint)
        console.log('\n✨ Migration completed successfully!\n')
    } catch (err) {
        console.error('\n❌ Migration failed:', err.message)
        console.error(err.stack)
        process.exit(1)
    }
}

main()
