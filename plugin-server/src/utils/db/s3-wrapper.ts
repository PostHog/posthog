import {
    DeleteObjectCommandInput,
    DeleteObjectCommandOutput,
    GetObjectCommandInput,
    GetObjectCommandOutput,
    ListObjectsV2CommandInput,
    ListObjectsV2CommandOutput,
    PutObjectCommandInput,
    S3,
    S3ClientConfig,
} from '@aws-sdk/client-s3';

export class S3Wrapper {
    s3: S3

    constructor(options: S3ClientConfig) {
        this.s3 = new S3(options)
    }

    async upload(params: PutObjectCommandInput): Promise<S3.ManagedUpload.SendData> {
        return this.s3.upload(params).promise()
    }

    async getObject(params: GetObjectCommandInput): Promise<GetObjectCommandOutput> {
        return this.s3.getObject(params).promise()
    }

    async deleteObject(params: DeleteObjectCommandInput): Promise<DeleteObjectCommandOutput> {
        return this.s3.deleteObject(params).promise()
    }

    async listObjectsV2(params: ListObjectsV2CommandInput): Promise<ListObjectsV2CommandOutput> {
        return this.s3.listObjectsV2(params).promise()
    }
}
