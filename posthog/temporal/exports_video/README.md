# Video Export Temporal Worker

This module handles video export workflows for session recordings using Temporal.

## Current Setup
- **Queue**: `general-purpose-task-queue` (shared with other workflows)
- **Dependencies**: Playwright + Chromium, ffmpeg (installed via mprocs)
- **Formats**: MP4, GIF, WebM

## Dedicated Worker Setup (Future)

If you want to move video exports to a dedicated worker for better resource isolation:

### 1. Update Worker Mappings
In `posthog/management/commands/start_temporal_worker.py`:
```python
# Move from GENERAL_PURPOSE_TASK_QUEUE to VIDEO_EXPORT_TASK_QUEUE
WORKFLOWS_DICT = {
    # ...
    VIDEO_EXPORT_TASK_QUEUE: VIDEO_EXPORT_WORKFLOWS,
}
ACTIVITIES_DICT = {
    # ...
    VIDEO_EXPORT_TASK_QUEUE: VIDEO_EXPORT_ACTIVITIES,
}
```

### 2. Update API
In `posthog/api/exports.py`:
```python
from posthog.constants import VIDEO_EXPORT_TASK_QUEUE

# Change task_queue parameter:
task_queue=VIDEO_EXPORT_TASK_QUEUE,
```

### 3. Add Dedicated Worker to mprocs
In `bin/mprocs.yaml`:
```yaml
temporal-worker-video-export:
    shell: |
        bin/check_kafka_clickhouse_up && bin/check_temporal_up && \
        # Playwright installation logic... \
        python manage.py start_temporal_worker --task-queue video-export-task-queue --metrics-port 8007
```

### 4. Production Deployment
Add to `.github/workflows/container-images-cd.yml`:
```yaml
- name: Check for changes that affect video export temporal worker
  id: check_changes_video_export_temporal_worker
  run: |
      echo "changed=$((git diff --name-only HEAD^ HEAD | grep -qE '^posthog/temporal/exports_video|^posthog/tasks/exports/video_exporter.py|^posthog/temporal/common|^posthog/management/commands/start_temporal_worker.py$|^pyproject.toml$|^bin/temporal-django-worker$|^Dockerfile$' && echo true) || echo false)" >> $GITHUB_OUTPUT

- name: Trigger Video Export Temporal Worker Cloud deployment
  if: steps.check_changes_video_export_temporal_worker.outputs.changed == 'true'
  uses: peter-evans/repository-dispatch@ff45666b9427631e3450c54a1bcbee4d9ff4d7c0 # v3
  with:
      token: ${{ steps.deployer.outputs.token }}
      repository: PostHog/charts
      event-type: commit_state_update
      client-payload: |
          {
            "values": {
              "image": {
                "sha": "${{ steps.build.outputs.digest }}"
              }
            },
            "release": "temporal-worker-video-export",
            "commit": ${{ toJson(github.event.head_commit) }},
            "repository": ${{ toJson(github.repository) }},
            "labels": ${{ toJson(steps.labels.outputs.labels) }},
            "timestamp": "${{ github.event.head_commit.timestamp }}"
          }
```

### 5. Create Helm Chart
Create `temporal-worker-video-export` chart in [PostHog/charts](https://github.com/PostHog/charts) repository based on existing `temporal-worker` chart.

## Benefits of Dedicated Worker
- Resource isolation (Playwright + ffmpeg are resource-intensive)
- Independent scaling
- Specialized Docker image with pre-installed dependencies
- Better observability and metrics
