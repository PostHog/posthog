# metrics4_samples overflows to S3 on this cluster. The disk balancer in posthog-cloud-infra moves
# its oldest parts off local disk.
database "posthog" {
  patch_table "metrics4_samples" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }
}
