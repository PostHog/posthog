import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
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

export async function uploadToS3(localPath: string, bucket: string, keyPrefix: string, id: string): Promise<string> {
    const key = `${keyPrefix}/${id}.mp4`

    await getS3Client().send(
        new PutObjectCommand({
            Bucket: bucket,
            Key: key,
            Body: fs.createReadStream(localPath),
            ContentType: 'video/mp4',
        })
    )

    return `s3://${bucket}/${key}`
}
