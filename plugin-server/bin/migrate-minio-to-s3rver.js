#!/usr/bin/env node

/**
 * migrate-minio-to-s3rver
 *
 * Migrates session recordings from MinIO to s3rver for local development.
 *
 * ⚠️  FOR LOCAL DEVELOPMENT ONLY ⚠️
 */

const {
    S3Client,
    ListObjectsV2Command,
    HeadObjectCommand,
    GetObjectCommand,
    PutObjectCommand,
} = require('@aws-sdk/client-s3')

// ============================================================================
// CONFIGURATION
// ============================================================================

const MINIO_ENDPOINT = 'http://localhost:19000'
const MINIO_ACCESS_KEY = 'object_storage_root_user'
const MINIO_SECRET_KEY = 'object_storage_root_password'

const S3RVER_ENDPOINT = 'http://localhost:4568'
const S3RVER_ACCESS_KEY = 'S3RVER'
const S3RVER_SECRET_KEY = 'S3RVER'

const BUCKET = 'posthog'
const PREFIX = 'session_recordings/'

// ============================================================================
// SAFETY CHECKS
// ============================================================================

function ensureLocalDevelopmentOnly() {
    console.log('\n🔒 Running safety checks...\n')

    // Check environment
    const nodeEnv = process.env.NODE_ENV?.toLowerCase()
    const isDebug = ['y', 'yes', 't', 'true', 'on', '1'].includes(String(process.env.DEBUG).toLowerCase())

    let isDev = false
    if (nodeEnv) {
        isDev = nodeEnv.startsWith('dev') || nodeEnv.startsWith('test')
    } else if (isDebug) {
        isDev = true
    }

    if (!isDev && nodeEnv !== undefined) {
        console.error('❌ SAFETY CHECK FAILED: Not running in development environment')
        console.error(`   NODE_ENV: ${process.env.NODE_ENV || 'not set'}`)
        console.error(`   DEBUG: ${process.env.DEBUG || 'not set'}`)
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        console.error('   Set NODE_ENV=development or DEBUG=1 to run.')
        process.exit(1)
    }

    console.log('✅ Safety checks passed\n')
}

// ============================================================================
// S3 CLIENT SETUP
// ============================================================================

function createS3Client(endpoint, accessKeyId, secretAccessKey) {
    return new S3Client({
        region: 'us-east-1',
        endpoint,
        credentials: {
            accessKeyId,
            secretAccessKey,
        },
        forcePathStyle: true,
    })
}

// ============================================================================
// MIGRATION LOGIC
// ============================================================================

async function listAllObjects(client, bucket, prefix) {
    const objects = []
    let continuationToken = undefined

    do {
        const command = new ListObjectsV2Command({
            Bucket: bucket,
            Prefix: prefix,
            ContinuationToken: continuationToken,
        })

        const response = await client.send(command)

        if (response.Contents) {
            objects.push(...response.Contents)
        }

        continuationToken = response.NextContinuationToken
    } while (continuationToken)

    return objects
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
    // Get object from source
    const getCommand = new GetObjectCommand({ Bucket: bucket, Key: key })
    const getResponse = await sourceClient.send(getCommand)

    // Convert stream to buffer
    const chunks = []
    for await (const chunk of getResponse.Body) {
        chunks.push(chunk)
    }
    const buffer = Buffer.concat(chunks)

    // Put to destination
    const putCommand = new PutObjectCommand({
        Bucket: bucket,
        Key: key,
        Body: buffer,
        ContentType: getResponse.ContentType,
    })

    await destClient.send(putCommand)

    return {
        size: buffer.length,
        etag: getResponse.ETag,
    }
}

class ProgressTracker {
    constructor(total) {
        this.total = total
        this.completed = 0
        this.skipped = 0
        this.failed = 0
        this.startTime = Date.now()
        this.bytesTransferred = 0
    }

    increment(type, bytes = 0) {
        if (type === 'completed') {
            this.completed++
            this.bytesTransferred += bytes
        } else if (type === 'failed') {
            this.failed++
        } else if (type === 'skipped') {
            this.skipped++
        }
    }

    print() {
        const elapsed = (Date.now() - this.startTime) / 1000
        const processed = this.completed + this.failed + this.skipped
        const percent = Math.round((processed / this.total) * 100)
        const rate = elapsed > 0 ? processed / elapsed : 0
        const remaining = rate > 0 ? (this.total - processed) / rate : 0
        const mbTransferred = (this.bytesTransferred / 1024 / 1024).toFixed(2)
        const mbPerSec = elapsed > 0 ? (this.bytesTransferred / 1024 / 1024 / elapsed).toFixed(2) : '0.00'

        const bar = '█'.repeat(Math.floor(percent / 2)) + '░'.repeat(50 - Math.floor(percent / 2))

        process.stdout.write(
            `\r[${bar}] ${percent}% | ${processed}/${this.total} | ` +
                `⏱ ${Math.floor(elapsed)}s | Est. ${Math.floor(remaining)}s | ` +
                `📊 ${mbTransferred} MB (${mbPerSec} MB/s) | ✓ ${this.completed} | ✗ ${this.failed} | ⊘ ${this.skipped}`
        )
    }

    clear() {
        process.stdout.write('\r' + ' '.repeat(150) + '\r')
    }
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
    console.log('\n🚀 Migrating session recordings from MinIO to s3rver')
    console.log('━'.repeat(80))

    // Safety checks
    ensureLocalDevelopmentOnly()

    // Create S3 clients
    console.log('Setting up S3 clients...')
    const minioClient = createS3Client(MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY)
    const s3rverClient = createS3Client(S3RVER_ENDPOINT, S3RVER_ACCESS_KEY, S3RVER_SECRET_KEY)
    console.log('✅ S3 clients ready\n')

    // Test connectivity
    console.log('Testing connectivity...')
    try {
        await minioClient.send(new HeadObjectCommand({ Bucket: BUCKET, Key: 'test' }))
    } catch (err) {
        if (err.$metadata?.httpStatusCode !== 404 && err.name !== 'NotFound') {
            console.error(`❌ Cannot connect to MinIO at ${MINIO_ENDPOINT}`)
            console.error(`   Error: ${err.message}`)
            console.error('   Make sure MinIO is running (./bin/start)')
            process.exit(1)
        }
    }
    console.log('✅ MinIO is accessible')

    try {
        await s3rverClient.send(new HeadObjectCommand({ Bucket: BUCKET, Key: 'test' }))
    } catch (err) {
        if (err.$metadata?.httpStatusCode !== 404 && err.name !== 'NotFound') {
            console.error(`❌ Cannot connect to s3rver at ${S3RVER_ENDPOINT}`)
            console.error(`   Error: ${err.message}`)
            console.error('   Make sure s3rver is running (docker-compose up s3rver)')
            process.exit(1)
        }
    }
    console.log('✅ s3rver is accessible\n')

    // Discover objects in MinIO
    console.log('Discovering session recordings in MinIO...')
    const allObjects = await listAllObjects(minioClient, BUCKET, PREFIX)

    if (allObjects.length === 0) {
        console.log('📭 No session recordings found in MinIO')
        console.log('✅ Migration complete (nothing to migrate)\n')
        return
    }

    const totalSize = allObjects.reduce((sum, obj) => sum + (obj.Size || 0), 0)
    const totalSizeMB = (totalSize / 1024 / 1024).toFixed(2)

    console.log(`📦 Found ${allObjects.length} objects (${totalSizeMB} MB)\n`)

    // Start migration
    console.log('Starting migration...\n')

    const progress = new ProgressTracker(allObjects.length)
    const failedObjects = []
    const workers = []
    const queue = [...allObjects]
    const WORKER_COUNT = 5

    for (let i = 0; i < WORKER_COUNT; i++) {
        workers.push(
            (async () => {
                while (true) {
                    const obj = queue.shift()
                    if (!obj) break

                    try {
                        // Check if already exists in s3rver
                        const exists = await objectExists(s3rverClient, BUCKET, obj.Key)

                        if (exists) {
                            progress.increment('skipped')
                        } else {
                            // Copy object
                            const result = await copyObject(minioClient, s3rverClient, BUCKET, obj.Key)
                            progress.increment('completed', result.size)
                        }
                    } catch (err) {
                        progress.increment('failed')
                        failedObjects.push({ key: obj.Key, error: err.message })
                    }

                    // Update progress every 5 objects
                    if ((progress.completed + progress.failed + progress.skipped) % 5 === 0) {
                        progress.print()
                    }
                }
            })()
        )
    }

    await Promise.all(workers)
    progress.clear()

    // Final summary
    console.log('\n━'.repeat(80))
    console.log('✅ Migration complete!\n')
    console.log('📊 Summary:')
    console.log(`   ✓ Successfully copied: ${progress.completed} objects`)
    console.log(`   ⊘ Already existed: ${progress.skipped} objects`)
    console.log(`   ✗ Failed: ${progress.failed} objects`)
    console.log(`   📦 Data transferred: ${(progress.bytesTransferred / 1024 / 1024).toFixed(2)} MB`)

    if (failedObjects.length > 0) {
        console.log(`\n⚠️  Failed objects:`)
        failedObjects.slice(0, 5).forEach((obj) => {
            console.log(`   • ${obj.key}`)
            console.log(`     Error: ${obj.error}`)
        })
        if (failedObjects.length > 5) {
            console.log(`   ... and ${failedObjects.length - 5} more`)
        }
        process.exit(1)
    }

    console.log('\n✅ All recordings migrated successfully!')
    console.log('\nNext steps:')
    console.log('   1. Restart services to use s3rver')
    console.log('   2. Test session recording playback')
    console.log('   3. Verify new recordings are written to s3rver\n')
}

// Run
main().catch((err) => {
    console.error(`\n❌ Fatal error: ${err.message}`)
    console.error(err.stack)
    process.exit(1)
})
