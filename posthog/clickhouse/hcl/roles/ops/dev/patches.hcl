# dev deltas to base objects. dev tracks prod-us on all three: it is where the
# prod-us experiments are tried first.
database "posthog" {
  patch_table "sharded_query_log_archive" {
    column "ProfileEvents2" {
      type = "JSON(max_dynamic_paths=0, OSCPUVirtualTimeMicroseconds UInt64, ReadBufferFromS3Bytes UInt64, RealTimeMicroseconds UInt64, S3AbortMultipartUpload UInt64, S3Clients UInt64, S3CompleteMultipartUpload UInt64, S3CopyObject UInt64, S3CreateMultipartUpload UInt64, S3DeleteObjects UInt64, S3GetObject UInt64, S3GetObjectAttributes UInt64, S3HeadObject UInt64, S3ListObjects UInt64, S3PutObject UInt64, S3UploadPart UInt64, S3UploadPartCopy UInt64, WriteBufferFromS3Bytes UInt64)"
    }
    settings = {
      storage_policy = "s3_tiered"
    }
  }

  patch_table "sharded_tophog" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog_new"
      replica_name = "{replica}"
    }
  }
}
