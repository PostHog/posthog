import { defaultConfig } from '../../config/config'

const aws = require('aws-sdk')

const { OBJECT_STORAGE_HOST, OBJECT_STORAGE_PORT, OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY } =
    defaultConfig

export const S3 = new aws.S3({
    endpoint: `http://${OBJECT_STORAGE_HOST}:${OBJECT_STORAGE_PORT}`,
    accessKeyId: OBJECT_STORAGE_ACCESS_KEY_ID,
    secretAccessKey: OBJECT_STORAGE_SECRET_ACCESS_KEY,
    s3ForcePathStyle: true, // needed with minio?
    signatureVersion: 'v4',
})
