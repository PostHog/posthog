---
cargo/posthog-cli: patch
---

Upload symbol sets with a presigned PUT when the server offers one. Presigned POST is an AWS S3 extension, so instances whose object storage does not implement it rejected every symbol set upload with 501 NotImplemented. The multipart POST stays in place for older servers.
