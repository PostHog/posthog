# Storage Migration Guide: MinIO → SeaweedFS

This guide explains how to migrate and sync object storage between MinIO and SeaweedFS for PostHog services.

## Overview

PostHog is gradually migrating from MinIO to SeaweedFS for object storage. This migration is done service-by-service to minimize risk and allow for easy rollback.

## Available Services

| Service                  | Folder                    | Description                             | Priority          | Risk Level             |
| ------------------------ | ------------------------- | --------------------------------------- | ----------------- | ---------------------- |
| `query-cache`            | `query_cache/`            | Query result cache                      | ⭐ Easiest        | Low (ephemeral)        |
| `session-recordings`     | `session_recordings/`     | Session recording blobs V2              | ⭐⭐ Easy         | Low (already migrated) |
| `session-recordings-lts` | `session_recordings_lts/` | Long-term storage recordings            | ⭐⭐ Easy         | Low                    |
| `media-uploads`          | `media_uploads/`          | User uploaded media                     | ⭐⭐⭐ Moderate   | Medium                 |
| `exports`                | `exports/`                | Exported assets (CSV, PNG, PDF, videos) | ⭐⭐⭐⭐ Moderate | Medium                 |
| `source-maps`            | `symbolsets/`             | Error tracking source maps              | ⭐⭐⭐⭐⭐ Hard   | High                   |

## Migration Modes

### 1. Migrate Mode (One-way copy)

Copies objects from source to destination once. Good for initial migrations.

```bash
# Migrate from MinIO to SeaweedFS
hogli deploy:migrate-storage --service query-cache --mode migrate

# Revert (copy from SeaweedFS back to MinIO)
hogli deploy:migrate-storage --service query-cache --mode migrate --revert
```

### 2. Sync Mode (Bidirectional)

Keeps both storages in sync by copying missing objects in both directions and resolving conflicts.

```bash
# Sync query cache between MinIO and SeaweedFS
hogli deploy:migrate-storage --service query-cache --mode sync

# Dry run to preview changes
hogli deploy:migrate-storage --service query-cache --mode sync --dry-run
```

## Conflict Resolution Strategies

When the same object exists in both storages with different content, the script resolves conflicts using these strategies:

| Strategy  | Behavior                                | Best For                         |
| --------- | --------------------------------------- | -------------------------------- |
| `newest`  | Keep the most recently modified version | Most services (default)          |
| `largest` | Keep the larger file                    | Media uploads (avoid corruption) |
| `skip`    | Don't sync conflicts                    | Query cache (can regenerate)     |

Override the default strategy:

```bash
hogli deploy:migrate-storage --service media-uploads --mode sync --conflict largest
```

## Quick Start: Recommended Migration Order

### Step 1: Query Cache (Practice Run)

Start with query cache because it's ephemeral and safe:

```bash
# Dry run to see what would happen
hogli deploy:migrate-storage --service query-cache --mode sync --dry-run

# Actually sync it
hogli deploy:migrate-storage --service query-cache --mode sync

# Enable SeaweedFS for query cache
export USE_SEAWEEDFS_FOR_QUERY_CACHE=true
```

### Step 2: Legacy Session Recordings

```bash
# Check what needs to sync
hogli deploy:migrate-storage --service session-recordings-lts --mode sync --dry-run

# Sync LTS recordings
hogli deploy:migrate-storage --service session-recordings-lts --mode sync
```

### Step 3: Media Uploads (if needed)

```bash
# Preview media sync
hogli deploy:migrate-storage --service media-uploads --mode sync --dry-run

# Sync media with 'largest' conflict resolution
hogli deploy:migrate-storage --service media-uploads --mode sync --conflict largest

# Enable SeaweedFS for media
export USE_SEAWEEDFS_FOR_MEDIA=true
```

### Step 4: Exports (if needed)

```bash
hogli deploy:migrate-storage --service exports --mode sync --dry-run
hogli deploy:migrate-storage --service exports --mode sync
export USE_SEAWEEDFS_FOR_EXPORTS=true
```

### Step 5: Source Maps (advanced, high risk)

```bash
# Only do this if you're confident
hogli deploy:migrate-storage --service source-maps --mode sync --dry-run
hogli deploy:migrate-storage --service source-maps --mode sync
export USE_SEAWEEDFS_FOR_SOURCE_MAPS=true
```

## Helper Script

For convenience, use the `sync-storage` helper script:

```bash
# Sync query cache
./bin/sync-storage query-cache

# Dry run for media uploads
./bin/sync-storage media-uploads --dry-run

# Preview exports sync
./bin/sync-storage exports -n
```

## Environment Variables

### For Local Development

```bash
# MinIO (default)
export OBJECT_STORAGE_ENDPOINT=http://localhost:19000
export OBJECT_STORAGE_ACCESS_KEY_ID=object_storage_root_user
export OBJECT_STORAGE_SECRET_ACCESS_KEY=object_storage_root_password

# SeaweedFS (new)
export SEAWEEDFS_ENDPOINT=http://localhost:8333
export SEAWEEDFS_ACCESS_KEY_ID=any
export SEAWEEDFS_SECRET_ACCESS_KEY=any

# Feature flags to use SeaweedFS
export USE_SEAWEEDFS_FOR_QUERY_CACHE=true
export USE_SEAWEEDFS_FOR_MEDIA=true
export USE_SEAWEEDFS_FOR_EXPORTS=true
export USE_SEAWEEDFS_FOR_SOURCE_MAPS=true
```

### For Hobby Deployments

Add to your `.env` file:

```bash
SEAWEEDFS_ENDPOINT=http://seaweedfs:8333
SEAWEEDFS_ACCESS_KEY_ID=any
SEAWEEDFS_SECRET_ACCESS_KEY=any

# Enable services one by one
USE_SEAWEEDFS_FOR_QUERY_CACHE=true
# USE_SEAWEEDFS_FOR_MEDIA=true
# USE_SEAWEEDFS_FOR_EXPORTS=true
```

## Advanced Options

### Resume Failed Migrations

If a migration is interrupted, resume from the last checkpoint:

```bash
hogli deploy:migrate-storage --service exports --mode migrate --resume
```

### Force Overwrite

Overwrite existing objects in destination (use with caution):

```bash
hogli deploy:migrate-storage --service query-cache --mode migrate --force
```

### Custom Worker Count

Speed up large migrations with more concurrent workers:

```bash
hogli deploy:migrate-storage --service exports --mode sync --workers 10
```

## Troubleshooting

### "Safety check failed: Non-local endpoint detected"

The script only runs on local development environments (localhost). For production, use different tooling.

### "Unable to clean or reset the repository" in CI

This is expected with container-created files. The CI workflows now handle this automatically.

### Objects failing to sync

Check the error messages in the output. Common issues:

- Network connectivity problems
- Permission issues
- Corrupted objects (check with `--dry-run` first)

### Conflict resolution not working as expected

Verify your conflict resolution strategy matches the service's needs:

- Use `newest` for time-sensitive data
- Use `largest` for media files
- Use `skip` for regenerable caches

## Rollback Strategy

If you need to roll back a service to MinIO:

```bash
# 1. Disable the SeaweedFS feature flag
export USE_SEAWEEDFS_FOR_MEDIA=false

# 2. Sync back to MinIO (revert direction)
hogli deploy:migrate-storage --service media-uploads --mode sync

# 3. Verify data is back in MinIO
# (check your MinIO console or run a test query)
```

## Monitoring

After migrating a service:

1. **Check storage usage**: Verify both storages have the expected data
2. **Test functionality**: Ensure the service works correctly with SeaweedFS
3. **Monitor logs**: Watch for any storage-related errors
4. **Run sync periodically**: Use sync mode to catch any drift

## Production Considerations

⚠️ **Important**: This script is designed for local development and hobby deployments only.

For production migrations:

1. Use a blue/green deployment strategy
2. Implement monitoring and alerting
3. Have a rollback plan ready
4. Test thoroughly in staging first
5. Migrate during low-traffic windows

## Need Help?

- Check the migration script help: `hogli deploy:migrate-storage --help`
- Review the sync-storage script: `./bin/sync-storage`
- Read the inline documentation in `plugin-server/bin/migrate-minio-to-seaweedfs.js`
