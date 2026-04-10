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

export async function uploadToS3(
    localPath: string,
    bucket: string,
    keyPrefix: string,
    id: string,
    onProgress?: () => void
): Promise<string> {
    const key = `${keyPrefix}/${id}.mp4`

    const upload = new Upload({
        client: getS3Client(),
        params: {
            Bucket: bucket,
            Key: key,
            Body: fs.createReadStream(localPath),
            ContentType: 'video/mp4',
        },
    })

    if (onProgress) {
        upload.on('httpUploadProgress', () => onProgress())
    }

    await upload.done()

    return `s3://${bucket}/${key}`
}
