#!/usr/bin/env node

/**
 * migrate-local-minio-to-localstack
 *
 * Migrates object storage data from local MinIO to LocalStack.
 *
 * ⚠️  FOR LOCAL DEVELOPMENT ONLY ⚠️
 * This script includes multiple safeguards to prevent running in production.
 * It only works with localhost endpoints.
 */

const {
    S3Client,
    ListObjectsV2Command,
    HeadObjectCommand,
    GetObjectCommand,
    PutObjectCommand,
    HeadBucketCommand,
    CreateBucketCommand,
} = require('@aws-sdk/client-s3')
const fs = require('fs')

// ============================================================================
// SERVICE DEFINITIONS
// ============================================================================
//
// Currently only session-recordings is supported.
// Other services (symbol-sets, batch-exports) will be added in future iterations.

const SERVICE_CONFIGS = {
    'session-recordings': {
        bucket: 'posthog',
        prefix: 'session_recordings/',
        description: 'Session recording batch files',
    },
}

// ============================================================================
// SAFETY CHECKS - PREVENT PRODUCTION USE
// ============================================================================

function isLocalEndpoint(endpoint) {
    const url = new URL(endpoint)
    const hostname = url.hostname.toLowerCase()

    // Only allow localhost, 127.0.0.1, or container names
    const allowedHosts = ['localhost', '127.0.0.1', '0.0.0.0', 'objectstorage', 'localstack']
    return allowedHosts.includes(hostname)
}

function ensureLocalDevelopmentOnly(minioEndpoint, localstackEndpoint) {
    console.log('\n🔒 Running safety checks...\n')

    // Check 1: Endpoints must be localhost
    if (!isLocalEndpoint(minioEndpoint)) {
        console.error('❌ SAFETY CHECK FAILED: MinIO endpoint is not localhost')
        console.error(`   Endpoint: ${minioEndpoint}`)
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        process.exit(1)
    }

    if (!isLocalEndpoint(localstackEndpoint)) {
        console.error('❌ SAFETY CHECK FAILED: LocalStack endpoint is not localhost')
        console.error(`   Endpoint: ${localstackEndpoint}`)
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        process.exit(1)
    }

    // Check 2: Environment must be development
    const env = process.env.NODE_ENV || 'development'
    if (env === 'production') {
        console.error('❌ SAFETY CHECK FAILED: NODE_ENV is set to production')
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        process.exit(1)
    }

    // Check 3: No AWS production indicators
    if (process.env.AWS_ROLE_ARN || process.env.AWS_WEB_IDENTITY_TOKEN_FILE) {
        console.error('❌ SAFETY CHECK FAILED: Production AWS credentials detected')
        console.error('   This script is for LOCAL DEVELOPMENT ONLY.')
        process.exit(1)
    }

    console.log('✅ Safety checks passed - running in local development mode\n')
}

// ============================================================================
// CLI ARGUMENT PARSER
// ============================================================================

function parseArgs() {
    const args = process.argv.slice(2)
    const options = {
        service: null,
        minioEndpoint: 'http://localhost:19000',
        localstackEndpoint: 'http://localhost:4566',
        minioAccessKey: 'object_storage_root_user',
        minioSecretKey: 'object_storage_root_password',
        localstackAccessKey: 'test',
        localstackSecretKey: 'test',
        workers: 10,
        dryRun: false,
        verifyOnly: false,
        checkpointFile: '/tmp/minio-localstack-migration.json',
        force: false,
        maxObjects: null,
    }

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--service':
                options.service = args[++i]
                break
            case '--minio-endpoint':
                options.minioEndpoint = args[++i]
                break
            case '--localstack-endpoint':
                options.localstackEndpoint = args[++i]
                break
            case '--minio-credentials':
                const minioCreds = args[++i].split(':')
                options.minioAccessKey = minioCreds[0]
                options.minioSecretKey = minioCreds[1]
                break
            case '--localstack-credentials':
                const localstackCreds = args[++i].split(':')
                options.localstackAccessKey = localstackCreds[0]
                options.localstackSecretKey = localstackCreds[1]
                break
            case '--workers':
                options.workers = parseInt(args[++i])
                break
            case '--dry-run':
                options.dryRun = true
                break
            case '--verify-only':
                options.verifyOnly = true
                break
            case '--checkpoint-file':
                options.checkpointFile = args[++i]
                break
            case '--force':
                options.force = true
                break
            case '--max-objects':
                options.maxObjects = parseInt(args[++i])
                break
            case '--help':
            case '-h':
                printHelp()
                process.exit(0)
            default:
                console.error(`Unknown option: ${args[i]}`)
                printHelp()
                process.exit(1)
        }
    }

    return options
}

function printHelp() {
    console.log(`
🚀 MinIO to LocalStack Migration Tool (LOCAL DEVELOPMENT ONLY)

Usage:
  ./bin/migrate-local-minio-to-localstack [options]

Options:
  --service <name>              Service to migrate: session-recordings (required)
  --minio-endpoint <url>        MinIO endpoint (default: http://localhost:19000)
  --localstack-endpoint <url>   LocalStack endpoint (default: http://localhost:4566)
  --minio-credentials <key:sec> MinIO credentials (default: object_storage_root_user:object_storage_root_password)
  --localstack-credentials <k:s> LocalStack credentials (default: test:test)
  --workers <n>                 Concurrent copy workers (default: 10)
  --dry-run                     Show what would be copied without copying
  --verify-only                 Only verify existing data, don't copy
  --checkpoint-file <path>      Progress file for resumption (default: /tmp/minio-localstack-migration.json)
  --force                       Overwrite existing objects (default: false)
  --max-objects <n>             Limit objects to migrate (for testing)
  --help, -h                    Show this help

Examples:
  # Migrate session recordings (dry run)
  ./bin/migrate-local-minio-to-localstack --service session-recordings --dry-run

  # Migrate session recordings (real)
  ./bin/migrate-local-minio-to-localstack --service session-recordings

  # Verify migration
  ./bin/migrate-local-minio-to-localstack --service session-recordings --verify-only

Available services:
  - session-recordings: Session recording batch files
  
Note: Other services (symbol-sets, batch-exports) will be added in future iterations.
`)
}

// ============================================================================
// CHECKPOINT MANAGER
// ============================================================================

class CheckpointManager {
    constructor(filepath) {
        this.filepath = filepath
        this.data = this.load()
    }

    load() {
        try {
            if (fs.existsSync(this.filepath)) {
                const content = fs.readFileSync(this.filepath, 'utf8')
                return JSON.parse(content)
            }
        } catch (err) {
            console.warn(`⚠️  Could not load checkpoint file: ${err.message}`)
        }

        return {
            version: 1,
            started_at: new Date().toISOString(),
            services: {},
        }
    }

    save() {
        try {
            this.data.last_updated = new Date().toISOString()
            fs.writeFileSync(this.filepath, JSON.stringify(this.data, null, 2))
        } catch (err) {
            console.error(`❌ Could not save checkpoint: ${err.message}`)
        }
    }

    getServiceData(serviceName) {
        if (!this.data.services[serviceName]) {
            this.data.services[serviceName] = {
                status: 'pending',
                total_objects: 0,
                completed_objects: 0,
                failed_objects: 0,
                skipped_objects: 0,
                completed_keys: [],
                failed_keys: [],
            }
        }
        return this.data.services[serviceName]
    }

    markCompleted(serviceName, key) {
        const service = this.getServiceData(serviceName)
        if (!service.completed_keys.includes(key)) {
            service.completed_keys.push(key)
            service.completed_objects++
        }
    }

    markFailed(serviceName, key, error) {
        const service = this.getServiceData(serviceName)
        service.failed_keys.push({ key, error: error.message, timestamp: new Date().toISOString() })
        service.failed_objects++
    }

    markSkipped(serviceName) {
        const service = this.getServiceData(serviceName)
        service.skipped_objects++
    }

    isCompleted(serviceName, key) {
        const service = this.getServiceData(serviceName)
        return service.completed_keys.includes(key)
    }
}

// ============================================================================
// S3 CLIENT SETUP
// ============================================================================

function createS3Client(endpoint, accessKeyId, secretAccessKey, region = 'us-east-1') {
    return new S3Client({
        region,
        endpoint,
        credentials: {
            accessKeyId,
            secretAccessKey,
        },
        forcePathStyle: true, // Required for MinIO and LocalStack
    })
}

// ============================================================================
// MIGRATION LOGIC
// ============================================================================

async function ensureBucketExists(client, endpoint, bucket) {
    try {
        await client.send(new HeadBucketCommand({ Bucket: bucket }))
        return true
    } catch (err) {
        if (err.name === 'NotFound' || err.$metadata?.httpStatusCode === 404) {
            // Bucket doesn't exist, try to create it
            console.log(`📦 Bucket '${bucket}' not found in ${endpoint}, creating it...`)
            try {
                await client.send(new CreateBucketCommand({ Bucket: bucket }))
                console.log(`✅ Successfully created bucket '${bucket}'`)
                return true
            } catch (createErr) {
                console.error(`❌ Failed to create bucket '${bucket}': ${createErr.message}`)
                return false
            }
        } else {
            console.error(`❌ Cannot connect to ${endpoint} bucket '${bucket}': ${err.message}`)
            return false
        }
    }
}

async function testConnectivity(client, endpoint, bucket) {
    try {
        await client.send(new HeadBucketCommand({ Bucket: bucket }))
        return true
    } catch (err) {
        console.error(`❌ Cannot connect to ${endpoint} bucket '${bucket}': ${err.message}`)
        return false
    }
}

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
    // Stream the object from source to destination
    const getCommand = new GetObjectCommand({ Bucket: bucket, Key: key })
    const getResponse = await sourceClient.send(getCommand)

    // Convert ReadableStream to Buffer
    const chunks = []
    for await (const chunk of getResponse.Body) {
        chunks.push(chunk)
    }
    const buffer = Buffer.concat(chunks)

    // Upload to destination
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
        this.failed = 0
        this.skipped = 0
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
        const rate = processed / elapsed
        const remaining = (this.total - processed) / rate
        const mbTransferred = (this.bytesTransferred / 1024 / 1024).toFixed(2)
        const mbPerSec = (this.bytesTransferred / 1024 / 1024 / elapsed).toFixed(2)

        const bar = '█'.repeat(Math.floor(percent / 2)) + '░'.repeat(50 - Math.floor(percent / 2))

        process.stdout.write(
            `\r[${bar}] ${percent}% | ${processed}/${this.total} objects | ` +
                `⏱ ${Math.floor(elapsed)}s | Est. ${Math.floor(remaining)}s remaining | ` +
                `📊 ${mbPerSec} MB/s | ✓ ${this.completed} | ✗ ${this.failed} | ⊘ ${this.skipped}`
        )
    }

    clear() {
        process.stdout.write('\r' + ' '.repeat(200) + '\r')
    }
}

async function migrateService(serviceName, config, options, checkpoint) {
    console.log(`\n${'='.repeat(80)}`)
    console.log(`📦 Migrating service: ${serviceName}`)
    console.log(`   Bucket: ${config.bucket}`)
    console.log(`   Prefix: ${config.prefix}`)
    console.log(`   Description: ${config.description}`)
    console.log(`${'='.repeat(80)}\n`)

    // Create S3 clients
    const minioClient = createS3Client(options.minioEndpoint, options.minioAccessKey, options.minioSecretKey)

    const localstackClient = createS3Client(
        options.localstackEndpoint,
        options.localstackAccessKey,
        options.localstackSecretKey
    )

    // Test connectivity and ensure buckets exist
    console.log('Testing connectivity...')
    const minioOk = await testConnectivity(minioClient, options.minioEndpoint, config.bucket)

    if (!minioOk) {
        console.error('❌ MinIO connectivity test failed. Skipping this service.')
        return false
    }

    console.log('✅ Connected to MinIO')

    // Ensure LocalStack bucket exists (auto-create if missing)
    const localstackOk = await ensureBucketExists(localstackClient, options.localstackEndpoint, config.bucket)

    if (!localstackOk) {
        console.error('❌ LocalStack connectivity test failed. Skipping this service.')
        return false
    }

    console.log('✅ Connected to LocalStack and bucket is ready\n')

    // Discover objects
    console.log('Discovering objects...')
    const allObjects = await listAllObjects(minioClient, config.bucket, config.prefix)

    if (allObjects.length === 0) {
        console.log('📭 No objects found. Nothing to migrate.')
        return true
    }

    const totalSize = allObjects.reduce((sum, obj) => sum + (obj.Size || 0), 0)
    const totalSizeMB = (totalSize / 1024 / 1024).toFixed(2)

    console.log(`📦 Found ${allObjects.length} objects (${totalSizeMB} MB)`)

    // Filter by checkpoint
    const serviceData = checkpoint.getServiceData(serviceName)
    const objectsToMigrate = allObjects.filter((obj) => !checkpoint.isCompleted(serviceName, obj.Key))

    if (objectsToMigrate.length < allObjects.length) {
        console.log(`✓ ${allObjects.length - objectsToMigrate.length} objects already completed (from checkpoint)`)
    }

    if (objectsToMigrate.length === 0) {
        console.log('✅ All objects already migrated!')
        return true
    }

    console.log(`→ Remaining: ${objectsToMigrate.length} objects\n`)

    // Apply max objects limit if set
    const objectsToProcess = options.maxObjects ? objectsToMigrate.slice(0, options.maxObjects) : objectsToMigrate

    if (options.maxObjects && objectsToProcess.length < objectsToMigrate.length) {
        console.log(`⚠️  Limited to ${options.maxObjects} objects (for testing)\n`)
    }

    // Dry run check
    if (options.dryRun) {
        console.log('🔍 DRY RUN - Would migrate:')
        objectsToProcess.slice(0, 10).forEach((obj) => {
            console.log(`   • ${obj.Key} (${(obj.Size / 1024).toFixed(2)} KB)`)
        })
        if (objectsToProcess.length > 10) {
            console.log(`   ... and ${objectsToProcess.length - 10} more objects`)
        }
        return true
    }

    // Verify only mode
    if (options.verifyOnly) {
        console.log('🔍 Verifying migration...')
        let verified = 0
        let missing = 0

        for (const obj of allObjects) {
            const exists = await objectExists(localstackClient, config.bucket, obj.Key)
            if (exists) {
                verified++
            } else {
                missing++
                console.log(`   ❌ Missing: ${obj.Key}`)
            }
        }

        console.log(`\nVerification complete:`)
        console.log(`   ✓ Found: ${verified}/${allObjects.length}`)
        console.log(`   ✗ Missing: ${missing}/${allObjects.length}`)

        return missing === 0
    }

    // Migration
    console.log(`Starting migration with ${options.workers} workers...\n`)

    serviceData.status = 'in_progress'
    serviceData.total_objects = allObjects.length
    checkpoint.save()

    const progress = new ProgressTracker(objectsToProcess.length)
    const failedObjects = []

    // Worker pool
    const workers = []
    const queue = [...objectsToProcess]

    for (let i = 0; i < options.workers; i++) {
        workers.push(
            (async () => {
                while (queue.length > 0) {
                    const obj = queue.shift()
                    if (!obj) break

                    try {
                        // Check if exists in destination
                        const exists = await objectExists(localstackClient, config.bucket, obj.Key)

                        if (exists && !options.force) {
                            checkpoint.markSkipped(serviceName)
                            progress.increment('skipped')
                        } else {
                            // Copy the object
                            const result = await copyObject(minioClient, localstackClient, config.bucket, obj.Key)
                            checkpoint.markCompleted(serviceName, obj.Key)
                            progress.increment('completed', result.size)
                        }
                    } catch (err) {
                        checkpoint.markFailed(serviceName, obj.Key, err)
                        progress.increment('failed')
                        failedObjects.push({ key: obj.Key, error: err.message })
                    }

                    // Update progress every 10 objects
                    if ((progress.completed + progress.failed + progress.skipped) % 10 === 0) {
                        progress.print()
                        checkpoint.save()
                    }
                }
            })()
        )
    }

    await Promise.all(workers)
    progress.clear()
    checkpoint.save()

    // Final summary
    console.log(`\n✅ Migration complete for ${serviceName}!\n`)
    console.log(`Summary:`)
    console.log(`   ✓ Successfully copied: ${progress.completed} objects`)
    console.log(`   ✗ Failed: ${progress.failed} objects`)
    console.log(`   ⊘ Skipped (already exist): ${progress.skipped} objects`)
    console.log(`   📊 Data transferred: ${(progress.bytesTransferred / 1024 / 1024).toFixed(2)} MB`)

    if (failedObjects.length > 0) {
        console.log(`\n⚠️  Failed objects:`)
        failedObjects.slice(0, 5).forEach((obj) => {
            console.log(`   • ${obj.key}`)
            console.log(`     Error: ${obj.error}`)
        })
        if (failedObjects.length > 5) {
            console.log(`   ... and ${failedObjects.length - 5} more`)
        }
    }

    serviceData.status = failedObjects.length === 0 ? 'completed' : 'completed_with_errors'
    checkpoint.save()

    return failedObjects.length === 0
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
    console.log('\n🚀 MinIO to LocalStack Migration Tool')
    console.log('━'.repeat(80))

    const options = parseArgs()

    if (!options.service) {
        console.error('\n❌ Error: --service is required\n')
        printHelp()
        process.exit(1)
    }

    // Validate service
    if (!SERVICE_CONFIGS[options.service]) {
        console.error(`\n❌ Error: Unknown service '${options.service}'`)
        console.error(`   Valid services: ${Object.keys(SERVICE_CONFIGS).join(', ')}\n`)
        console.error(`   Note: Only session-recordings is currently supported.`)
        console.error(`   Other services will be added in future iterations.\n`)
        process.exit(1)
    }

    // Safety checks
    ensureLocalDevelopmentOnly(options.minioEndpoint, options.localstackEndpoint)

    // Print configuration
    console.log('Configuration:')
    console.log(`   Service:        ${options.service}`)
    console.log(`   MinIO:          ${options.minioEndpoint}`)
    console.log(`   LocalStack:     ${options.localstackEndpoint}`)
    console.log(`   Workers:        ${options.workers}`)
    console.log(`   Checkpoint:     ${options.checkpointFile}`)
    console.log(`   Dry run:        ${options.dryRun}`)
    console.log(`   Verify only:    ${options.verifyOnly}`)
    console.log(`   Force:          ${options.force}`)
    if (options.maxObjects) {
        console.log(`   Max objects:    ${options.maxObjects}`)
    }
    console.log('━'.repeat(80))

    // Load checkpoint
    const checkpoint = new CheckpointManager(options.checkpointFile)

    // Currently only single service migration is supported
    const servicesToMigrate = [options.service]

    let allSuccessful = true

    for (const serviceName of servicesToMigrate) {
        const config = SERVICE_CONFIGS[serviceName]
        const success = await migrateService(serviceName, config, options, checkpoint)
        if (!success) {
            allSuccessful = false
        }
    }

    // Final report
    console.log(`\n${'='.repeat(80)}`)
    console.log('📊 FINAL REPORT')
    console.log('='.repeat(80))

    for (const serviceName of servicesToMigrate) {
        const serviceData = checkpoint.getServiceData(serviceName)
        console.log(`\n${serviceName}:`)
        console.log(`   Status: ${serviceData.status}`)
        console.log(`   Total: ${serviceData.total_objects}`)
        console.log(`   Completed: ${serviceData.completed_objects}`)
        console.log(`   Failed: ${serviceData.failed_objects}`)
        console.log(`   Skipped: ${serviceData.skipped_objects}`)
    }

    console.log(`\n${'='.repeat(80)}\n`)

    if (!allSuccessful) {
        console.log('⚠️  Some migrations had errors. Check the output above for details.')
        console.log(`   Checkpoint saved to: ${options.checkpointFile}`)
        console.log(`   Re-run the same command to retry failed objects.\n`)
        process.exit(1)
    }

    console.log('✅ All migrations completed successfully!\n')

    if (!options.dryRun && !options.verifyOnly) {
        console.log('Next steps:')
        console.log('   1. Verify the migration:')
        console.log(`      ./bin/migrate-local-minio-to-localstack --service ${options.service} --verify-only`)
        console.log('   2. Update service configuration to use LocalStack')
        console.log('   3. Test that the service can read from LocalStack')
        console.log('   4. Once confirmed, you can stop writing to MinIO\n')
    }
}

// Run
main().catch((err) => {
    console.error(`\n❌ Fatal error: ${err.message}`)
    console.error(err.stack)
    process.exit(1)
})
