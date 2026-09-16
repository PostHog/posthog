# Hobby: moving object storage off MinIO

PostHog's hobby stack used two object stores: MinIO on `objectstorage:19000` for general storage, and SeaweedFS on `seaweedfs:8333` for session replay v2.
MinIO stopped publishing Docker images, so the `objectstorage` service now runs SeaweedFS as well.

SeaweedFS cannot read the MinIO on-disk format, and there is no in-place conversion.
The service starts on a new `objectstorage-data` volume, and the MinIO data stays where it is, on the `objectstorage` volume.

## What becomes unavailable

Until you copy the objects across, PostHog cannot read:

- exported assets (CSV, PNG, PDF, video)
- uploaded media, such as images in notebooks
- error tracking symbol sets, so stack traces stay unsymbolicated
- session recordings that are still in MinIO

Postgres and ClickHouse are untouched.
Events, persons, insights, dashboards, feature flags and experiments all survive the upgrade.

## Option 1: copy the objects after the upgrade

This is the usual path.
`bin/upgrade-hobby` asks you to acknowledge the change before it pulls the new version, and it keeps the old volume.

Upgrade first, wait for the stack to come up, then run this from the directory that holds your `docker-compose.yml`:

```bash
./posthog/bin/migrate-storage-hobby --dry-run   # see what would be copied
./posthog/bin/migrate-storage-hobby             # copy it
```

The script starts a temporary MinIO container on the stack's network, mounted on the old volume, and copies bucket contents through the running services.
It copies:

- the whole `posthog` bucket into `objectstorage`, so a prefix that no list here mentions still comes across
- the `ai-blobs` bucket into `objectstorage`
- session recordings into `seaweedfs`
- symbol sets into `seaweedfs` as well, because cymbal reads them there while Django reads them from `objectstorage`

The query cache is the one thing left behind, because PostHog rebuilds it.

The copy skips objects that already exist in the destination, so it is safe to run again after a failure.
It exits non-zero if any object failed, and it only suggests deleting the old volume after a complete run.

Check your data in PostHog before you free the disk space:

```bash
docker volume rm <project>_objectstorage
```

The script prints the volume name it read.
It picks that volume by name (`<project>_objectstorage`) and refuses to guess when a host holds more than one, so pass `--volume <id>` if you run several installs on one machine.

## Upgrading through the installer instead

`bin/hobby-installer` does not run `bin/upgrade-hobby`, so it cannot show that prompt.
Its preflight checks warn instead, whenever the legacy volume is still on the host, and ask you to confirm before the upgrade continues.
The warning clears once you copy the objects across and delete the old volume.

## Option 2: stay on your current version

Answer `N` at the upgrade prompt.
Nothing changes, and you keep a running MinIO.
Copy the `posthog` bucket out with any S3 client against `http://127.0.0.1:19000`, with access key `object_storage_root_user` and secret `object_storage_root_password`, then upgrade.

This option matters most if you cannot pull `quay.io/minio/minio`, which option 1 needs.

## If the copy does not work

The temporary container reads a pinned MinIO release from Quay.
MinIO archived its source repository in October 2025, so that image can disappear.
If the pull fails, the objects are still on the volume.
Mount it on any host that can still run MinIO, start MinIO against it, and copy the bucket out with an S3 client.

## Why the anonymous identity is off in hobby

Dev and CI register an `anonymous` SeaweedFS identity with Admin rights, so unsigned clients keep working.
Hobby does not, because Caddy proxies `/posthog/*` straight to `objectstorage`.
An anonymous identity there makes every object readable and writable from the internet.
Only the `posthog` identity is registered, so SeaweedFS rejects unsigned requests and the presigned URLs Django hands out keep working.
