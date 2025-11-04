#!/usr/bin/env node

/**
 * Migration and sync script for object storage between MinIO and SeaweedFS
 *
 * This script supports:
 * - One-way migration (MinIO → SeaweedFS or SeaweedFS → MinIO)
 * - Bidirectional sync (keeps both storages in sync)
 * - Multiple services (session recordings, exports, media uploads, etc.)
 *
 * Usage:
 *   node bin/migrate-minio-to-seaweedfs.js [options]
 *
 * Options:
 *   --service <name>       Service to migrate (default: session-recordings)
 *   --mode <mode>          Mode: migrate | sync (default: migrate)
 *   --force                Overwrite existing objects in destination
 *   --dry-run              Show what would be migrated without copying
 *   --workers <n>          Number of concurrent workers (default: 5)
 *   --resume               Resume from last checkpoint
 *   --revert               Copy from SeaweedFS back to MinIO (reverse direction)
 *   --conflict <strategy>  Conflict resolution: newest | largest | skip (default: newest)
 *   --help                 Show this help message
 *
 * Modes:
 *   migrate  One-way copy from source to destination
 *   sync     Bidirectional sync - copies missing objects in both directions
 *
 * Services:
 *   session-recordings      Session recording blobs (V2)
 *   session-recordings-lts  Long-term storage session recordings
 *   query-cache            Query result cache
 *   media-uploads          User uploaded media
 *   exports                Exported assets (CSV, PNG, PDF, videos)
 *   source-maps            Error tracking source maps
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
        description: 'Session recording blobs (V2)',
        bidirectional: true,
        conflictResolution: 'newest',
    },
    'session-recordings-lts': {
        bucket: 'posthog',
        prefix: 'session_recordings_lts/',
        description: 'Long-term storage session recordings',
        bidirectional: true,
        conflictResolution: 'newest',
    },
    'query-cache': {
        bucket: 'posthog',
        prefix: 'query_cache/',
        description: 'Query result cache (ephemeral)',
        bidirectional: true,
        conflictResolution: 'skip', // Cache can be regenerated
    },
    'media-uploads': {
        bucket: 'posthog',
        prefix: 'media_uploads/',
        description: 'User uploaded media files',
        bidirectional: true,
        conflictResolution: 'largest', // Keep largest to avoid corrupted files
        critical: true,
    },
    exports: {
        bucket: 'posthog',
        prefix: 'exports/',
        description: 'Exported assets (CSV, PNG, PDF, videos)',
        bidirectional: true,
        conflictResolution: 'newest',
        critical: true,
    },
    'source-maps': {
        bucket: 'posthog',
        prefix: 'symbolsets/',
        description: 'Error tracking source maps',
        bidirectional: true,
        conflictResolution: 'newest',
        critical: true,
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
        mode: 'migrate',
        force: false,
        dryRun: false,
        workers: 5,
        resume: false,
        revert: false,
        conflictResolution: 'newest',
    }

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--service':
                options.service = args[++i]
                break
            case '--mode':
                options.mode = args[++i]
                if (!['migrate', 'sync'].includes(options.mode)) {
                    console.error(`Invalid mode: ${options.mode}. Must be 'migrate' or 'sync'`)
                    process.exit(1)
                }
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
            case '--conflict':
                options.conflictResolution = args[++i]
                if (!['newest', 'largest', 'skip'].includes(options.conflictResolution)) {
                    console.error(
                        `Invalid conflict resolution: ${options.conflictResolution}. Must be 'newest', 'largest', or 'skip'`
                    )
                    process.exit(1)
                }
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

async function getObjectMetadata(client, bucket, key) {
    try {
        const response = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }))
        return {
            Size: response.ContentLength,
            LastModified: response.LastModified,
            ETag: response.ETag,
        }
    } catch (err) {
        if (err.name === 'NotFound' || err.$metadata?.httpStatusCode === 404) {
            return null
        }
        throw err
    }
}

async function objectsAreSame(sourceClient, destClient, bucket, key) {
    const [sourceMetadata, destMetadata] = await Promise.all([
        getObjectMetadata(sourceClient, bucket, key),
        getObjectMetadata(destClient, bucket, key),
    ])

    // If destination doesn't exist, they're not the same
    if (!destMetadata) {
        return false
    }

    // If source doesn't exist (shouldn't happen), consider them different
    if (!sourceMetadata) {
        return false
    }

    // Use the needsSync logic (inverted)
    return !needsSync(sourceMetadata, destMetadata)
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

async function listAllObjectsWithMetadata(client, bucket, prefix) {
    const allObjects = []
    let continuationToken = undefined

    do {
        const command = new ListObjectsV2Command({
            Bucket: bucket,
            Prefix: prefix,
            ContinuationToken: continuationToken,
        })
        const response = await client.send(command)

        if (response.Contents) {
            allObjects.push(...response.Contents)
        }

        continuationToken = response.NextContinuationToken
    } while (continuationToken)

    return allObjects
}

function needsSync(objA, objB) {
    // Different size = different content
    if (objA.Size !== objB.Size) return true

    // Different modification time (with tolerance of 2 seconds for clock skew)
    const timeDiff = Math.abs(new Date(objA.LastModified) - new Date(objB.LastModified))
    if (timeDiff > 2000) return true

    // ETag comparison if available (not all S3 implementations provide this)
    if (objA.ETag && objB.ETag && objA.ETag !== objB.ETag) return true

    return false
}

async function resolveConflict(conflict, strategy, minioClient, seaweedfsClient, bucket) {
    const { key, minioObj, seaweedfsObj } = conflict

    let winnerObj, winnerClient, loserClient, winnerName

    switch (strategy) {
        case 'newest':
            const minioTime = new Date(minioObj.LastModified)
            const seaweedfsTime = new Date(seaweedfsObj.LastModified)
            if (minioTime > seaweedfsTime) {
                winnerObj = minioObj
                winnerClient = minioClient
                loserClient = seaweedfsClient
                winnerName = 'MinIO'
            } else {
                winnerObj = seaweedfsObj
                winnerClient = seaweedfsClient
                loserClient = minioClient
                winnerName = 'SeaweedFS'
            }
            break

        case 'largest':
            if (minioObj.Size > seaweedfsObj.Size) {
                winnerObj = minioObj
                winnerClient = minioClient
                loserClient = seaweedfsClient
                winnerName = 'MinIO'
            } else {
                winnerObj = seaweedfsObj
                winnerClient = seaweedfsClient
                loserClient = minioClient
                winnerName = 'SeaweedFS'
            }
            break

        case 'skip':
            return { action: 'skipped', key }

        default:
            throw new Error(`Unknown conflict resolution strategy: ${strategy}`)
    }

    // Copy winner to loser
    await copyObject(winnerClient, loserClient, bucket, key)
    return { action: 'resolved', key, winner: winnerName, size: winnerObj.Size }
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
                        // Check if objects are identical (same size, timestamp, content)
                        const areSame = await objectsAreSame(sourceClient, destClient, config.bucket, obj.Key)
                        if (areSame && !options.force) {
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
    console.log(`⊘  Skipped:   ${progress.skipped} (already identical in destination)`)
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

async function syncService(serviceName, config, options, checkpoint) {
    console.log(`\n${'='.repeat(80)}`)
    console.log(`🔄 Syncing: ${serviceName}`)
    console.log(`   ${config.description}`)
    console.log(`   Mode: Bidirectional Sync`)
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

    // Ensure bucket exists in both
    await ensureBucketExists(minioClient, config.bucket)
    await ensureBucketExists(seaweedfsClient, config.bucket)

    // Test connectivity
    const minioOk = await testConnectivity(minioClient, 'MinIO', config.bucket)
    const seaweedfsOk = await testConnectivity(seaweedfsClient, 'SeaweedFS', config.bucket)

    if (!minioOk || !seaweedfsOk) {
        throw new Error('Failed to connect to storage backends')
    }

    // List objects from both sides
    console.log(`📋 Listing objects from both storages...`)
    const [minioObjects, seaweedfsObjects] = await Promise.all([
        listAllObjectsWithMetadata(minioClient, config.bucket, config.prefix),
        listAllObjectsWithMetadata(seaweedfsClient, config.bucket, config.prefix),
    ])

    console.log(`✅ MinIO: ${minioObjects.length} objects`)
    console.log(`✅ SeaweedFS: ${seaweedfsObjects.length} objects`)

    // Build key maps
    const minioMap = new Map(minioObjects.map((o) => [o.Key, o]))
    const seaweedfsMap = new Map(seaweedfsObjects.map((o) => [o.Key, o]))

    // Find differences
    const onlyInMinio = []
    const onlyInSeaweedfs = []
    const conflicts = []

    for (const [key, minioObj] of minioMap) {
        if (!seaweedfsMap.has(key)) {
            onlyInMinio.push(minioObj)
        } else {
            const seaweedfsObj = seaweedfsMap.get(key)
            if (needsSync(minioObj, seaweedfsObj)) {
                conflicts.push({ key, minioObj, seaweedfsObj })
            }
        }
    }

    for (const [key, seaweedfsObj] of seaweedfsMap) {
        if (!minioMap.has(key)) {
            onlyInSeaweedfs.push(seaweedfsObj)
        }
    }

    // Calculate objects already in sync
    const totalObjects = minioObjects.length + seaweedfsObjects.length
    const inBothStorages = minioObjects.filter((obj) => seaweedfsMap.has(obj.Key)).length
    const alreadyInSync = inBothStorages - conflicts.length

    console.log(`\n📊 Sync Analysis:`)
    console.log(`   Total objects: ${totalObjects}`)
    console.log(`   Already in sync: ${alreadyInSync} ✓`)
    console.log(`   MinIO → SeaweedFS: ${onlyInMinio.length} objects`)
    console.log(`   SeaweedFS → MinIO: ${onlyInSeaweedfs.length} objects`)
    console.log(`   Conflicts to resolve: ${conflicts.length} objects`)

    const totalOperations = onlyInMinio.length + onlyInSeaweedfs.length + conflicts.length

    if (totalOperations === 0) {
        console.log(`\n✨ Storages are already in sync! No changes needed.`)
        return
    }

    if (options.dryRun) {
        console.log('\n🔍 DRY RUN MODE - No objects will be copied\n')
        if (onlyInMinio.length > 0) {
            console.log('Would copy MinIO → SeaweedFS:')
            onlyInMinio.slice(0, 5).forEach((obj) => {
                console.log(`  - ${obj.Key} (${(obj.Size / 1024).toFixed(2)} KB)`)
            })
            if (onlyInMinio.length > 5) console.log(`  ... and ${onlyInMinio.length - 5} more`)
        }
        if (onlyInSeaweedfs.length > 0) {
            console.log('\nWould copy SeaweedFS → MinIO:')
            onlyInSeaweedfs.slice(0, 5).forEach((obj) => {
                console.log(`  - ${obj.Key} (${(obj.Size / 1024).toFixed(2)} KB)`)
            })
            if (onlyInSeaweedfs.length > 5) console.log(`  ... and ${onlyInSeaweedfs.length - 5} more`)
        }
        if (conflicts.length > 0) {
            const resolution = options.conflictResolution || config.conflictResolution
            console.log(`\nWould resolve ${conflicts.length} conflicts using strategy: ${resolution}`)
            conflicts.slice(0, 3).forEach((c) => {
                console.log(`  - ${c.key}:`)
                console.log(`    MinIO: ${(c.minioObj.Size / 1024).toFixed(2)} KB, ${c.minioObj.LastModified}`)
                console.log(
                    `    SeaweedFS: ${(c.seaweedfsObj.Size / 1024).toFixed(2)} KB, ${c.seaweedfsObj.LastModified}`
                )
            })
            if (conflicts.length > 3) console.log(`  ... and ${conflicts.length - 3} more`)
        }
        return
    }

    // Sync in both directions
    console.log(`\n🚀 Starting bidirectional sync with ${options.workers} workers...\n`)
    const progress = new ProgressTracker(totalOperations)
    const failedObjects = []

    // Copy MinIO → SeaweedFS
    console.log(`📤 Copying ${onlyInMinio.length} objects from MinIO to SeaweedFS...`)
    const queue1 = [...onlyInMinio]
    const workers1 = []
    for (let i = 0; i < options.workers; i++) {
        workers1.push(
            (async () => {
                while (true) {
                    const obj = queue1.shift()
                    if (!obj) break
                    try {
                        const result = await copyObject(minioClient, seaweedfsClient, config.bucket, obj.Key)
                        progress.increment('completed', result.size)
                    } catch (err) {
                        progress.increment('failed')
                        failedObjects.push({ key: obj.Key, error: err.message, direction: 'MinIO→SeaweedFS' })
                    }
                }
            })()
        )
    }
    await Promise.all(workers1)

    // Copy SeaweedFS → MinIO
    console.log(`📥 Copying ${onlyInSeaweedfs.length} objects from SeaweedFS to MinIO...`)
    const queue2 = [...onlyInSeaweedfs]
    const workers2 = []
    for (let i = 0; i < options.workers; i++) {
        workers2.push(
            (async () => {
                while (true) {
                    const obj = queue2.shift()
                    if (!obj) break
                    try {
                        const result = await copyObject(seaweedfsClient, minioClient, config.bucket, obj.Key)
                        progress.increment('completed', result.size)
                    } catch (err) {
                        progress.increment('failed')
                        failedObjects.push({ key: obj.Key, error: err.message, direction: 'SeaweedFS→MinIO' })
                    }
                }
            })()
        )
    }
    await Promise.all(workers2)

    // Resolve conflicts
    if (conflicts.length > 0) {
        const resolution = options.conflictResolution || config.conflictResolution
        console.log(`\n⚔️  Resolving ${conflicts.length} conflicts using strategy: ${resolution}...`)
        const queue3 = [...conflicts]
        const workers3 = []
        for (let i = 0; i < options.workers; i++) {
            workers3.push(
                (async () => {
                    while (true) {
                        const conflict = queue3.shift()
                        if (!conflict) break
                        try {
                            const result = await resolveConflict(
                                conflict,
                                resolution,
                                minioClient,
                                seaweedfsClient,
                                config.bucket
                            )
                            if (result.action === 'skipped') {
                                progress.increment('skipped')
                            } else {
                                progress.increment('completed', result.size)
                            }
                        } catch (err) {
                            progress.increment('failed')
                            failedObjects.push({ key: conflict.key, error: err.message, direction: 'conflict' })
                        }
                    }
                })()
            )
        }
        await Promise.all(workers3)
    }

    progress.finish()

    // Summary
    console.log(`\n${'='.repeat(80)}`)
    console.log('📊 Sync Summary')
    console.log(`${'='.repeat(80)}`)
    console.log(`✅ Synced: ${progress.completed}`)
    console.log(`⊘  Skipped: ${progress.skipped}`)
    console.log(`✗  Failed: ${progress.failed}`)
    console.log(`📦 Data transferred: ${(progress.bytesTransferred / 1024 / 1024).toFixed(2)} MB`)
    console.log(`⏱  Total time: ${Math.floor((Date.now() - progress.startTime) / 1000)}s`)

    if (failedObjects.length > 0) {
        console.log(`\n❌ Failed objects:`)
        failedObjects.slice(0, 10).forEach((obj) => {
            console.log(`   [${obj.direction}] ${obj.key}: ${obj.error}`)
        })
        if (failedObjects.length > 10) {
            console.log(`   ... and ${failedObjects.length - 10} more`)
        }
    }

    if (config.critical && failedObjects.length > 0) {
        console.log(`\n⚠️  WARNING: This is a CRITICAL service and ${failedObjects.length} objects failed to sync!`)
    }
}

async function main() {
    const options = parseArgs()

    let title
    if (options.mode === 'sync') {
        title = 'Bidirectional Storage Sync Tool'
    } else {
        title = options.revert ? 'SeaweedFS to MinIO Migration Tool' : 'MinIO to SeaweedFS Migration Tool'
    }
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
        if (options.mode === 'sync') {
            if (!config.bidirectional) {
                console.warn(`⚠️  Warning: Service '${options.service}' is not configured for bidirectional sync.`)
                console.warn(`   Proceeding anyway, but this service may not be suitable for sync mode.`)
            }
            await syncService(options.service, config, options, checkpoint)
            console.log('\n✨ Sync completed successfully!\n')
        } else {
            await migrateService(options.service, config, options, checkpoint)
            console.log('\n✨ Migration completed successfully!\n')
        }
    } catch (err) {
        console.error(`\n❌ ${options.mode === 'sync' ? 'Sync' : 'Migration'} failed:`, err.message)
        console.error(err.stack)
        process.exit(1)
    }
}

main()
