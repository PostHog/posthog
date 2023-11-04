import { S3 } from 'aws-sdk'

export class S3Wrapper {
    s3: S3

    constructor(options: S3.Types.ClientConfiguration) {
        this.s3 = new S3(options)
    }

    async upload(params: S3.Types.PutObjectRequest): Promise<S3.ManagedUpload.SendData> {
        return this.s3.upload(params).promise()
    }

    async getObject(params: S3.GetObjectRequest): Promise<S3.Types.GetObjectOutput> {
        return this.s3.getObject(params).promise()
    }

    async deleteObject(params: S3.DeleteObjectRequest): Promise<S3.Types.DeleteObjectOutput> {
        return this.s3.deleteObject(params).promise()
    }

    async listObjectsV2(params: S3.ListObjectsV2Request): Promise<S3.Types.ListObjectsV2Output> {
        return this.s3.listObjectsV2(params).promise()
    }
}
