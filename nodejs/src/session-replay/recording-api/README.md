# Recording API

This module provides the HTTP API for serving session recording playback data and handling recording deletions.

## Overview

The `RecordingApi` exposes REST endpoints that:

- **Serve recording blocks** decrypted from object storage (S3) for playback
- **Delete recordings** via crypto-shredding (deleting the encryption key, rendering data permanently unreadable)
- **Emit deletion metadata** to ClickHouse and clean up associated PostgreSQL records

## Endpoints

- `GET /api/projects/:team_id/recordings/:session_id/block` - Fetch and decrypt a recording block
- `DELETE /api/projects/:team_id/recordings/:session_id` - Delete a recording via crypto-shredding
