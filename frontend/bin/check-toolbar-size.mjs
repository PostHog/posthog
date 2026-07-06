import fs from 'fs'
import path from 'path'

// Fail the build if dist/toolbar.js grows past the size CloudFront will still gzip.
//
// CloudFront only compresses responses whose body is between 1,000 and 10,000,000 bytes
// (https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/ServingCompressedFiles.html).
// Once the toolbar bundle crosses 10,000,000 bytes it is served uncompressed, so a bundle that
// tips just over the line jumps from ~1.7 MB on the wire to its full ~10 MB. That cliff is
// invisible in a size-delta comment, so guard it with a hard failure instead.
//
// When this fails, shrink the bundle rather than raising the limit — see the deny-list in
// frontend/toolbar-config.mjs for the mechanism (heavy libraries the toolbar never renders can
// be cut at resolve time, since the IIFE bundle has no code-splitting to defer them).
const MAX_BYTES = 10_000_000

function humanBytes(bytes) {
    return `${(bytes / 1_000_000).toFixed(2)} MB (${bytes.toLocaleString()} bytes)`
}

function main() {
    const filePath = 'dist/toolbar.js'
    const absPath = path.resolve(process.cwd(), filePath)

    let bytes
    try {
        bytes = fs.statSync(absPath).size
    } catch {
        console.error(`✗ Could not read ${filePath} — build the toolbar before running this check.`)
        process.exit(1)
    }

    if (bytes > MAX_BYTES) {
        console.error(
            `✗ Toolbar bundle is ${humanBytes(bytes)}, over the ${humanBytes(MAX_BYTES)} CloudFront gzip limit.`
        )
        console.error(
            '  CloudFront serves files this large uncompressed. Shrink the bundle (see frontend/toolbar-config.mjs).'
        )
        process.exit(1)
    }

    console.info(`✓ Toolbar bundle is ${humanBytes(bytes)}, within the ${humanBytes(MAX_BYTES)} CloudFront gzip limit.`)
}

main()
