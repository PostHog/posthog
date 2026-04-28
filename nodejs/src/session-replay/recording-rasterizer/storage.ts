import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import * as fs from 'fs'

import { config } from './config'

let s3Client: S3Client | null = null

function getS3Client(): S3Client {
    if (!s3Client) {
        s3Client = new S3Client({
            region: config.s3Region,
            ...(config.s3Endpoint ? { endpoint: config.s3Endpoint, forcePathStyle: true } : {}),
        })
    }
    return s3Client
}

const FORMAT_META: Record<string, { ext: string; contentType: string }> = {
    mp4: { ext: 'mp4', contentType: 'video/mp4' },
    webm: { ext: 'webm', contentType: 'video/webm' },
    gif: { ext: 'gif', contentType: 'image/gif' },
}

export async function uploadToS3(
    localPath: string,
    bucket: string,
    keyPrefix: string,
    id: string,
    format: 'mp4' | 'webm' | 'gif' = 'mp4',
    onProgress?: () => void
): Promise<string> {
    const { ext, contentType } = FORMAT_META[format] || FORMAT_META.mp4
    const key = `${keyPrefix}/${id}.${ext}`

    const upload = new Upload({
        client: getS3Client(),
        params: {
            Bucket: bucket,
            Key: key,
            Body: fs.createReadStream(localPath),
            ContentType: contentType,
        },
    })

    if (onProgress) {
        upload.on('httpUploadProgress', () => onProgress())
    }

    await upload.done()

    return `s3://${bucket}/${key}`
}
