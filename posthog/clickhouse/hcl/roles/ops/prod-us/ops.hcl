# OPS prod-us env layer — events distributed proxies, sharded_tophog (tophog_new zoo_path)
#
# Generated/maintained as the declarative source of truth for the OPS ClickHouse cluster.
# Resolve with: hclexp load -layer <base>,<...>

database "posthog" {
  # An extra ProfileEvents2 JSON column on the base sharded_query_log_archive
  # table, running on dev and prod-us. Additive patch so the shared base stays
  # region-agnostic; fold it in once it reaches prod-eu, drop it if it ends.
  patch_table "sharded_query_log_archive" {
    column "ProfileEvents2" {
      type = "JSON(max_dynamic_paths=0, OSCPUVirtualTimeMicroseconds UInt64, ReadBufferFromS3Bytes UInt64, RealTimeMicroseconds UInt64, S3AbortMultipartUpload UInt64, S3Clients UInt64, S3CompleteMultipartUpload UInt64, S3CopyObject UInt64, S3CreateMultipartUpload UInt64, S3DeleteObjects UInt64, S3GetObject UInt64, S3GetObjectAttributes UInt64, S3HeadObject UInt64, S3ListObjects UInt64, S3PutObject UInt64, S3UploadPart UInt64, S3UploadPartCopy UInt64, WriteBufferFromS3Bytes UInt64)"
    }
    settings = {
      storage_policy = "s3_tiered"
    }
  }
}
