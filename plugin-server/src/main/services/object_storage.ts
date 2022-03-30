const aws = require('aws-sdk')

export const S3 = new aws.S3({
    endpoint: 'http://localhost:19000',
    accessKeyId: 'object_storage_root_user',
    secretAccessKey: 'object_storage_root_password',
    s3ForcePathStyle: true, // needed with minio?
    signatureVersion: 'v4',
})
