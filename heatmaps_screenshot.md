# Heatmaps Screenshot Feature Implementation Plan

## Overview

Replace the current iframe-based approach in heatmaps with a screenshot-based solution to overcome iframe restrictions and capture full page height for better heatmap visualization.

## Problem Statement

Current issues with iframe approach:

1. **X-Frame-Options restrictions** - Many websites block iframe embedding for security
2. **Limited height visibility** - Only shows top portion of websites, missing important heatmap data
3. **CSP restrictions** - Content Security Policy blocks iframe loading
4. **Inconsistent rendering** - Different behavior across browsers and websites

## Solution Architecture

Replace iframe with website screenshots overlaid with heatmap data, providing:

- Full page capture regardless of iframe restrictions
- Complete page height visibility
- Consistent rendering across all websites
- Better performance (no interactive elements needed)

---

## Backend Implementation

### 1. Database Changes

#### New HeatmapScreenshot Model

**File**: `posthog/models/heatmap_screenshot.py`

```python
from django.db import models
from posthog.models.utils import UUIDTModel, RootTeamMixin
from posthog.models.uploaded_media import save_content_to_object_storage
import hashlib

class HeatmapScreenshot(UUIDTModel, RootTeamMixin):
    """
    Stores website screenshots for heatmap visualization.
    Unlike ExportedAsset, these are long-lived and manually managed.
    """

    # URL and viewport configuration (follows PostHog patterns for viewport storage)
    url = models.URLField(max_length=2048)
    # Store viewport as JSON to match PostHog patterns for flexible dimension storage
    viewport_config = models.JSONField(default=dict, help_text="Viewport configuration: {width: int, height?: int}")

    # Actual screenshot dimensions after capture (separate fields for indexing, like sessions)
    actual_width = models.PositiveIntegerField(null=True, blank=True)
    actual_height = models.PositiveIntegerField(null=True, blank=True)

    # Content storage - simplified to object storage only
    content_location = models.TextField(null=True, blank=True, max_length=1000)  # Object storage path

    # Cache key for deduplication (hash of url + viewport_config)
    cache_key = models.CharField(max_length=32, unique=True, db_index=True)

    # Status tracking
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(auto_now_add=True)  # For cleanup of unused screenshots

    # User who requested this screenshot
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            # Optimized composite indexes for common query patterns
            models.Index(fields=['team', 'status', 'created_at']),  # For admin/monitoring queries
            models.Index(fields=['team', 'url', 'viewport_config']),  # For duplicate detection
            models.Index(fields=['status', 'last_used_at']),  # For cleanup operations
            models.Index(fields=['team', 'cache_key']),  # For fast lookups
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'cache_key'],
                name='unique_team_cache_key'
            )
        ]

    @property
    def has_content(self) -> bool:
        return self.content_location is not None

    @property
    def viewport_width(self) -> int:
        """Get viewport width from config"""
        return self.viewport_config.get('width', 1400)

    @property
    def viewport_height(self) -> int | None:
        """Get viewport height from config"""
        return self.viewport_config.get('height')

    @classmethod
    def generate_cache_key(cls, url: str, viewport_config: dict) -> str:
        """Generate cache key for deduplication"""
        # Normalize viewport config for consistent hashing
        normalized_config = {
            'width': viewport_config.get('width', 1400),
            'height': viewport_config.get('height')  # None if not specified
        }
        key_data = f"{url}:{normalized_config['width']}:{normalized_config['height'] or 'auto'}"
        return hashlib.md5(key_data.encode()).hexdigest()

    @classmethod
    def get_or_create_for_url(cls, team, url: str, viewport_width: int,
                             viewport_height: int | None = None,
                             created_by=None) -> tuple['HeatmapScreenshot', bool]:
        """Get existing screenshot or create new one"""
        viewport_config = {'width': viewport_width}
        if viewport_height is not None:
            viewport_config['height'] = viewport_height

        cache_key = cls.generate_cache_key(url, viewport_config)

        screenshot, created = cls.objects.get_or_create(
            team=team,
            cache_key=cache_key,
            defaults={
                'url': url,
                'viewport_config': viewport_config,
                'created_by': created_by,
            }
        )

        if not created:
            # Update last_used_at for existing screenshots
            screenshot.last_used_at = timezone.now()
            screenshot.save(update_fields=['last_used_at'])

        return screenshot, created

    def save_screenshot_content(self, content: bytes) -> None:
        """Save screenshot content to object storage"""
        from posthog.models.uploaded_media import object_storage

        path_parts = [
            "heatmap_screenshots",
            f"team-{self.team.id}",
            f"{self.cache_key}.png"
        ]
        object_path = "/".join(path_parts)

        object_storage.write(object_path, content)
        self.content_location = object_path
        self.save(update_fields=['content_location'])

    def get_content(self) -> bytes | None:
        """Get screenshot content from object storage"""
        if self.content_location:
            from posthog.models.uploaded_media import object_storage
            return object_storage.read_bytes(self.content_location)
        return None

    def mark_as_failed(self, error_message: str) -> None:
        """Mark screenshot as failed with error message"""
        self.status = self.Status.FAILED
        self.error_message = error_message
        self.save(update_fields=['status', 'error_message', 'updated_at'])

    def mark_as_completed(self, actual_width: int, actual_height: int) -> None:
        """Mark screenshot as completed with actual dimensions"""
        self.status = self.Status.COMPLETED
        self.actual_width = actual_width
        self.actual_height = actual_height
        self.save(update_fields=['status', 'actual_width', 'actual_height', 'updated_at'])

    @classmethod
    def cleanup_unused_screenshots(cls, days_unused: int = 30) -> int:
        """Clean up screenshots not used for specified days"""
        from django.utils import timezone
        from datetime import timedelta

        cutoff_date = timezone.now() - timedelta(days=days_unused)
        unused_screenshots = cls.objects.filter(last_used_at__lt=cutoff_date)

        count = unused_screenshots.count()
        unused_screenshots.delete()

        return count
```

#### Migration File

**File**: `posthog/migrations/XXXX_add_heatmap_screenshot_model.py`

```python
from django.db import migrations, models
import django.db.models.deletion
from posthog.models.utils import UUIDT

class Migration(migrations.Migration):
    dependencies = [
        ('posthog', 'XXXX_previous_migration'),
    ]

    operations = [
        migrations.CreateModel(
            name='HeatmapScreenshot',
            fields=[
                ('id', models.UUIDField(default=UUIDT, primary_key=True, serialize=False)),
                ('url', models.URLField(max_length=2048)),
                ('viewport_config', models.JSONField(default=dict, help_text="Viewport configuration: {width: int, height?: int}")),
                ('actual_width', models.PositiveIntegerField(blank=True, null=True)),
                ('actual_height', models.PositiveIntegerField(blank=True, null=True)),
                ('content', models.BinaryField(blank=True, null=True)),
                ('content_location', models.TextField(blank=True, max_length=1000, null=True)),
                ('cache_key', models.CharField(db_index=True, max_length=32, unique=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_used_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='posthog.user')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='posthog.team')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['team', 'cache_key'], name='heatmap_screenshot_team_cache_idx'),
                    models.Index(fields=['team', 'url'], name='heatmap_screenshot_team_url_idx'),
                    models.Index(fields=['status'], name='heatmap_screenshot_status_idx'),
                    models.Index(fields=['last_used_at'], name='heatmap_screenshot_last_used_idx'),
                ],
                'constraints': [
                    models.UniqueConstraint(fields=['team', 'cache_key'], name='unique_team_cache_key'),
                ],
            },
            bases=(models.Model,),
        ),
    ]
```

### 2. Screenshot API Endpoint

#### Add to Existing HeatmapViewSet

**File**: `posthog/heatmaps/heatmaps_api.py`

Add simple screenshot endpoints to existing heatmaps API:

- `POST /api/projects/{team_id}/heatmaps/screenshots/` - Request screenshot
- `GET /api/projects/{team_id}/heatmaps/screenshots/{id}/content/` - Get screenshot image

```python
# Add these serializers to the existing heatmaps_api.py file

class HeatmapScreenshotRequestSerializer(serializers.Serializer):
    url = serializers.URLField(required=True, max_length=2048)
    viewport_width = serializers.IntegerField(required=False, default=1400, min_value=320, max_value=1920)
    viewport_height = serializers.IntegerField(required=False, min_value=200, max_value=4000)
    force_refresh = serializers.BooleanField(required=False, default=False)

    def validate_url(self, value):
        """Comprehensive URL validation with security checks"""
        from urllib.parse import urlparse
        import socket
        import ipaddress

        parsed = urlparse(value)

        # Basic validation
        if not parsed.scheme in ['http', 'https']:
            raise serializers.ValidationError("Only HTTP/HTTPS URLs allowed")

        # Block private/internal IPs
        if parsed.hostname:
            try:
                ip = socket.gethostbyname(parsed.hostname)
                ip_obj = ipaddress.ip_address(ip)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    raise serializers.ValidationError("Private/internal IPs not allowed")
            except (socket.gaierror, ValueError):
                raise serializers.ValidationError("Invalid hostname")

        return value

class HeatmapScreenshotSerializer(serializers.ModelSerializer):
    dimensions = serializers.SerializerMethodField()
    content_url = serializers.SerializerMethodField()

    class Meta:
        model = HeatmapScreenshot
        fields = [
            'id', 'url', 'viewport_config', 'status', 'error_message',
            'dimensions', 'content_url', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'status', 'error_message', 'created_at', 'updated_at']

    def get_dimensions(self, obj):
        if obj.actual_width and obj.actual_height:
            return {'width': obj.actual_width, 'height': obj.actual_height}
        return None

    def get_content_url(self, obj):
        if obj.has_content:
            return f"/api/projects/{obj.team.id}/heatmaps/screenshots/{obj.id}/content/"
        return None

# Add these methods to the existing HeatmapViewSet class

class HeatmapViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # ... existing code ...

    @ratelimit(key='team', rate='50/h', method='POST')
    @action(methods=["POST"], detail=False, url_path="screenshots")
    def create_screenshot(self, request: request.Request) -> response.Response:
        """Request a new screenshot or return existing one"""
        serializer = HeatmapScreenshotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        url = serializer.validated_data['url']
        viewport_width = serializer.validated_data['viewport_width']
        viewport_height = serializer.validated_data.get('viewport_height')
        force_refresh = serializer.validated_data['force_refresh']

        # Get or create screenshot
        screenshot, created = HeatmapScreenshot.get_or_create_for_url(
            team=self.team,
            url=url,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            created_by=request.user if hasattr(request, 'user') else None
        )

        # If force refresh or screenshot failed, regenerate
        if force_refresh or screenshot.status == HeatmapScreenshot.Status.FAILED:
            screenshot.status = HeatmapScreenshot.Status.PENDING
            screenshot.error_message = None
            screenshot.save(update_fields=['status', 'error_message', 'updated_at'])
            created = True

        # Queue screenshot generation if needed
        if created or screenshot.status == HeatmapScreenshot.Status.PENDING:
            screenshot.status = HeatmapScreenshot.Status.PROCESSING
            screenshot.save(update_fields=['status', 'updated_at'])

            # Queue celery task
            from posthog.tasks.heatmap_screenshots import generate_heatmap_screenshot
            generate_heatmap_screenshot.delay(screenshot.id)

        return response.Response(
            HeatmapScreenshotSerializer(screenshot).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    @action(methods=["GET"], detail=False, url_path="screenshots/<str:screenshot_id>/content")
    def screenshot_content(self, request: request.Request, screenshot_id: str) -> HttpResponse:
        """Serve screenshot image content"""
        try:
            screenshot = HeatmapScreenshot.objects.get(id=screenshot_id, team=self.team)

            if not screenshot.has_content:
                return HttpResponse(
                    'Screenshot not ready',
                    status=404,
                    content_type='text/plain'
                )

            content = screenshot.get_content()
            if not content:
                return HttpResponse(
                    'Screenshot content not found',
                    status=404,
                    content_type='text/plain'
                )

            # Update last_used_at
            screenshot.last_used_at = timezone.now()
            screenshot.save(update_fields=['last_used_at'])

            response = HttpResponse(content, content_type='image/png')
            response['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
            response['Content-Disposition'] = f'inline; filename="screenshot-{screenshot.cache_key}.png"'

            return response

        except HeatmapScreenshot.DoesNotExist:
            return HttpResponse(
                'Screenshot not found',
                status=404,
                content_type='text/plain'
            )
```

**Request/Response Models**:

```python
# Request
{
    "url": "https://example.com/page",
    "viewport_width": 1400,
    "viewport_height": null,  # optional, auto-detected if null
    "force_refresh": false
}

# Response
{
    "id": "uuid",
    "url": "https://example.com/page",
    "viewport_width": 1400,
    "viewport_height": null,
    "status": "completed",  # pending, processing, completed, failed
    "error_message": null,
    "dimensions": {
        "width": 1400,
        "height": 2847
    },
    "content_url": "/api/projects/123/heatmap_screenshots/uuid/content/",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:01:30Z",
    "last_used_at": "2024-01-01T00:01:30Z"
}
```

### 3. Screenshot Generator (Celery Task)

#### New Celery Task Module

**File**: `posthog/tasks/heatmap_screenshots.py`

```python
import os
import time
import uuid
import tempfile
from typing import Optional, Tuple

import structlog
import posthoganalytics
from celery import shared_task
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

from posthog.exceptions_capture import capture_exception
from posthog.models.heatmap_screenshot import HeatmapScreenshot
from posthog.tasks.utils import CeleryQueue
from PIL import Image
import io

logger = structlog.get_logger(__name__)

def compress_screenshot(image_data: bytes) -> bytes:
    """Compress screenshot for web delivery"""
    image = Image.open(io.BytesIO(image_data))

    # Convert to RGB and compress
    if image.mode != 'RGB':
        image = image.convert('RGB')

    output = io.BytesIO()
    image.save(output, format='JPEG', quality=80, optimize=True)
    return output.getvalue()

TMP_DIR = "/tmp"
DEFAULT_WIDTH = 1400
DEFAULT_HEIGHT = 800
MAX_HEIGHT = 4000

# Simple Chrome driver setup
def get_driver() -> webdriver.Chrome:
    """Chrome driver setup for external websites"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-web-security")

    if os.environ.get("CHROMEDRIVER_BIN"):
        service = webdriver.ChromeService(executable_path=os.environ["CHROMEDRIVER_BIN"])
        return webdriver.Chrome(service=service, options=options)

    return webdriver.Chrome(
        service=Service(ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()),
        options=options,
    )

def _take_website_screenshot(
    image_path: str,
    url: str,
    viewport_width: int = DEFAULT_WIDTH,
    viewport_height: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Take screenshot of external website.
    Returns (actual_width, actual_height)

    Reuses dimension detection logic from image_exporter.py
    """
    driver: Optional[webdriver.Chrome] = None
    try:
        driver = get_driver()

        # Set initial window size
        initial_height = viewport_height or DEFAULT_HEIGHT
        driver.set_window_size(viewport_width, initial_height)

        # Navigate to URL
        driver.get(url)
        posthoganalytics.tag("url_to_render", url)

        # Wait for page to load (basic wait, no specific selectors for external sites)
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            # Continue anyway, some sites may not fully load
            pass

        # Wait a bit more for dynamic content
        driver.execute_script("return new Promise(resolve => setTimeout(resolve, 2000))")

        # Get page dimensions - adapted from image_exporter.py
        dimensions = driver.execute_script("""
            const body = document.body;
            const html = document.documentElement;

            const height = Math.max(
                body.scrollHeight || 0,
                body.offsetHeight || 0,
                html.clientHeight || 0,
                html.scrollHeight || 0,
                html.offsetHeight || 0
            );

            const width = Math.max(
                body.scrollWidth || 0,
                body.offsetWidth || 0,
                html.clientWidth || 0,
                html.scrollWidth || 0,
                html.offsetWidth || 0
            );

            return { width: width, height: height };
        """)

        actual_width = max(viewport_width, min(1920, dimensions.get('width', viewport_width)))
        actual_height = min(MAX_HEIGHT, dimensions.get('height', initial_height))

        # Set final window size
        driver.set_window_size(actual_width, actual_height)

        # Allow a moment for resizing
        driver.execute_script("return new Promise(resolve => setTimeout(resolve, 500))")

        # Take screenshot
        driver.save_screenshot(image_path)

        return actual_width, actual_height

    except Exception as e:
        # Error handling pattern from image_exporter.py
        with posthoganalytics.new_context():
            posthoganalytics.tag("url_to_render", url)
            if driver:
                try:
                    driver.save_screenshot(image_path)
                    posthoganalytics.tag("image_path", image_path)
                except Exception:
                    pass
        capture_exception(e)
        raise
    finally:
        if driver:
            driver.quit()

@shared_task(
    bind=True,
    max_retries=3,
    retry_backoff=2,
    retry_backoff_max=60,
    rate_limit='10/m',  # Max 10 screenshots per minute per worker
    queue=CeleryQueue.EXPORTS.value,  # Reuse exports queue
)
def generate_heatmap_screenshot(self, screenshot_id: str) -> None:
    """
    Generate screenshot for HeatmapScreenshot model.

    Args:
        screenshot_id: UUID of HeatmapScreenshot instance
    """
    image_path = None

    try:
        # Get screenshot record
        screenshot = HeatmapScreenshot.objects.get(id=screenshot_id)

        logger.info("heatmap_screenshot.starting",
                   screenshot_id=screenshot_id,
                   url=screenshot.url,
                   width=screenshot.viewport_width)

        # Create temp file
        image_id = str(uuid.uuid4())
        image_path = os.path.join(TMP_DIR, f"heatmap_screenshot_{image_id}.png")

        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        # Take screenshot
        actual_width, actual_height = _take_website_screenshot(
            image_path=image_path,
            url=screenshot.url,
            viewport_width=screenshot.viewport_width,
            viewport_height=screenshot.viewport_height,
        )

        # Read and compress screenshot content
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()

        # Compress image for optimal storage and delivery
        compressed_data = compress_screenshot(image_data)

        # Save to screenshot model
        screenshot.save_screenshot_content(compressed_data)
        screenshot.mark_as_completed(actual_width, actual_height)

        # Cleanup temp file
        os.remove(image_path)

        logger.info("heatmap_screenshot.completed",
                   screenshot_id=screenshot_id,
                   actual_width=actual_width,
                   actual_height=actual_height)

    except HeatmapScreenshot.DoesNotExist:
        logger.error("heatmap_screenshot.not_found", screenshot_id=screenshot_id)
        # Don't retry for missing records
        return

    except Exception as e:
        # Cleanup temp file on error
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        logger.error("heatmap_screenshot.failed",
                    screenshot_id=screenshot_id,
                    error=str(e),
                    exc_info=True)

        # Update screenshot with error
        try:
            screenshot = HeatmapScreenshot.objects.get(id=screenshot_id)
            screenshot.mark_as_failed(str(e))
        except HeatmapScreenshot.DoesNotExist:
            pass

        # Capture exception for monitoring
        with posthoganalytics.new_context():
            posthoganalytics.tag("screenshot_id", screenshot_id)
            capture_exception(e)

        # Retry on certain errors
        if self.request.retries < self.max_retries:
            # Retry on network errors, timeouts, etc.
            if any(error_type in str(e).lower() for error_type in
                   ['timeout', 'network', 'connection', 'chrome']):
                logger.info("heatmap_screenshot.retrying",
                           screenshot_id=screenshot_id,
                           retry=self.request.retries + 1)
                raise self.retry(countdown=60 * (2 ** self.request.retries))

        # Don't retry for permanent failures (invalid URL, etc.)
        raise
```

#### Cleanup Task

**File**: `posthog/tasks/heatmap_screenshots.py` (continued)

```python
@shared_task(ignore_result=True, queue=CeleryQueue.EXPORTS.value)
def cleanup_old_heatmap_screenshots() -> None:
    """Clean up unused heatmap screenshots older than 30 days"""
    try:
        deleted_count = HeatmapScreenshot.cleanup_unused_screenshots(days_unused=30)
        logger.info("heatmap_screenshot.cleanup_completed", deleted_count=deleted_count)
    except Exception as e:
        logger.error("heatmap_screenshot.cleanup_failed", error=str(e))
        capture_exception(e)
```

#### Task Registration

**File**: `posthog/tasks/__init__.py`

Add to imports:

```python
from . import (
    # ... existing imports
    heatmap_screenshots,
)

__all__ = [
    # ... existing exports
    "heatmap_screenshots",
]
```

### 4. Caching & Storage Strategy

**Cache Key Generation** (built into `HeatmapScreenshot` model):

```python
@classmethod
def generate_cache_key(cls, url: str, viewport_width: int, viewport_height: int | None) -> str:
    key_data = f"{url}:{viewport_width}:{viewport_height or 'auto'}"
    return hashlib.md5(key_data.encode()).hexdigest()
```

**Storage Strategy**:

- **Long-lived storage**: Unlike exports, screenshots persist until manually deleted
- **Object storage**: Reuses existing object storage infrastructure
- **Database fallback**: Small screenshots can be stored in database
- **Automatic cleanup**: Unused screenshots cleaned up after 30 days via `last_used_at`

**Deduplication**:

- **Unique constraint**: `(team, cache_key)` prevents duplicates
- **Automatic reuse**: `get_or_create_for_url()` returns existing screenshots
- **Usage tracking**: `last_used_at` updated on each access

### 5. URL Routing

**No additional routing needed** - the screenshot endpoints are added as actions to the existing `HeatmapViewSet` which is already registered at:

```python
# Already exists in posthog/api/routing.py
router.register(
    r"projects/(?P<parent_lookup_team_id>[^/.]+)/heatmaps",
    HeatmapViewSet,
    "project_heatmaps"
)
```

This gives us the clean URL structure:

- `POST /api/projects/{team_id}/heatmaps/screenshots/`
- `GET /api/projects/{team_id}/heatmaps/screenshots/{id}/`
- `DELETE /api/projects/{team_id}/heatmaps/screenshots/{id}/`
- `GET /api/projects/{team_id}/heatmaps/screenshots/{id}/content/`

### 6. Scheduled Cleanup

**File**: `posthog/tasks/scheduled.py`

```python
# Add periodic cleanup task
@setup_periodic_tasks.connect
def setup_heatmap_screenshot_cleanup(sender, **kwargs):
    from posthog.tasks.heatmap_screenshots import cleanup_old_heatmap_screenshots

    # Run cleanup daily at 2 AM
    sender.add_periodic_task(
        crontab(hour=2, minute=0),
        cleanup_old_heatmap_screenshots.s(),
        name='cleanup_old_heatmap_screenshots'
    )
```

---

## Celery Task Implementation

### Task Configuration

**New dedicated celery task**: `generate_heatmap_screenshot`

**Task Properties**:

- Queue: `CeleryQueue.EXPORTS` (reuse existing exports queue)
- Retries: 3 with exponential backoff (2^retry seconds)
- Max retry delay: 60 seconds
- Bind: True (for retry functionality)

### Error Handling

**Retry Conditions** (automatic retry):

- Network timeouts (`timeout` in error message)
- Chrome crashes (`chrome` in error message)
- Connection failures (`network`, `connection` in error message)

**Permanent Failures** (no retry):

- Invalid URLs
- Websites that block all automated access
- Malformed responses
- Missing screenshot records

**Error Storage**:

- Store error message in `HeatmapScreenshot.error_message` field
- Update status to `FAILED`
- Capture exceptions with PostHog analytics
- Structured logging for debugging

### Cleanup Strategy

**Automatic cleanup task**: `cleanup_old_heatmap_screenshots`

- Runs daily at 2 AM via cron schedule
- Removes screenshots unused for 30+ days
- Based on `last_used_at` timestamp
- Prevents unlimited storage growth

---

## Frontend Implementation

### 1. New Screenshot Browser Component

#### Replace IframeHeatmapBrowser

**File**: `frontend/src/scenes/heatmaps/ScreenshotHeatmapBrowser.tsx`

```typescript
export function ScreenshotHeatmapBrowser({
    iframeRef, // Keep for compatibility
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element {
    const [screenshotData, setScreenshotData] = useState<ScreenshotResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // Screenshot management logic
    // Polling for completion
    // Error handling
    // Dimension management
}
```

#### Screenshot API Integration

**File**: `frontend/src/lib/api/heatmapScreenshots.ts`

```typescript
export interface HeatmapScreenshotRequest {
    url: string
    viewport_width: number
    viewport_height?: number
    force_refresh?: boolean
}

export interface HeatmapScreenshotResponse {
    id: string
    url: string
    viewport_width: number
    viewport_height?: number
    status: 'pending' | 'processing' | 'completed' | 'failed'
    error_message?: string
    dimensions?: { width: number; height: number }
    content_url?: string
    created_at: string
    updated_at: string
    last_used_at: string
}

export const heatmapScreenshotsApi = {
    create: async (teamId: number, request: HeatmapScreenshotRequest): Promise<HeatmapScreenshotResponse> => {
        const response = await api.post(`/api/projects/${teamId}/heatmaps/screenshots/`, request)
        return response.data
    },

    get: async (teamId: number, id: string): Promise<HeatmapScreenshotResponse> => {
        const response = await api.get(`/api/projects/${teamId}/heatmaps/screenshots/${id}/`)
        return response.data
    },

    delete: async (teamId: number, id: string): Promise<void> => {
        await api.delete(`/api/projects/${teamId}/heatmaps/screenshots/${id}/`)
    },

    getContentUrl: (teamId: number, id: string): string => {
        return `/api/projects/${teamId}/heatmaps/screenshots/${id}/content/`
    },
}
```

### 2. Logic Updates

#### Integrate into Existing Heatmaps Logic

**File**: `frontend/src/scenes/heatmaps/heatmapsBrowserLogic.ts`

Add screenshot state directly to existing logic:

```typescript
// Add to existing reducers
screenshotData: [
    null as HeatmapScreenshotResponse | null,
    {
        setScreenshotData: (_, { data }) => data,
        resetScreenshot: () => null,
    }
],
screenshotLoading: [
    false,
    {
        requestScreenshot: () => true,
        setScreenshotData: () => false,
        setScreenshotError: () => false,
    }
],
screenshotError: [
    null as string | null,
    {
        setScreenshotError: (_, { error }) => error,
        requestScreenshot: () => null,
    }
],

// Add to existing actions
requestScreenshot: (url: string, viewport_width?: number) => ({ url, viewport_width }),
setScreenshotData: (data: HeatmapScreenshotResponse | null) => ({ data }),
setScreenshotError: (error: string | null) => ({ error }),
resetScreenshot: true,
```

### 3. Component Updates

#### Update Main Browser Component

**File**: `frontend/src/scenes/heatmaps/HeatmapsBrowser.tsx`

Replace iframe rendering logic:

```typescript
// Replace this section:
{!isBrowserUrlAuthorized ? (
    <ForbiddenURL />
) : !isBrowserUrlValid ? (
    <InvalidURL />
) : (
    <IframeHeatmapBrowser iframeRef={iframeRef} />  // OLD
)}

// With:
{!isBrowserUrlAuthorized ? (
    <ForbiddenURL />
) : !isBrowserUrlValid ? (
    <InvalidURL />
) : (
    <ScreenshotHeatmapBrowser iframeRef={iframeRef} />  // NEW
)}
```

#### Update HeatmapCanvas

**File**: `lib/components/heatmaps/HeatmapCanvas.tsx`

Add support for screenshot dimensions:

```typescript
interface HeatmapCanvasProps {
    // ... existing props
    screenshotDimensions?: { width: number; height: number } | null
}

// Update positioning calculations to use screenshot dimensions
// instead of iframe dimensions when available
```

### 4. User Experience Improvements

#### Manual Heatmap Loading (Key UX Change)

**Replace automatic loading with explicit user action:**

Instead of automatically requesting screenshots when URLs are typed, add a "Load Heatmap" button that only triggers screenshot generation when clicked.

**File**: `frontend/src/scenes/heatmaps/HeatmapsBrowser.tsx`

```typescript
function UrlSearchHeader({ iframeRef }: { iframeRef?: React.MutableRefObject<HTMLIFrameElement | null> }): JSX.Element {
    // ... existing logic ...

    // Add screenshot logic
    const { screenshotData, screenshotLoading, screenshotError } = useValues(screenshotBrowserLogic)
    const { requestScreenshot, resetScreenshot } = useActions(screenshotBrowserLogic)

    const handleLoadHeatmap = () => {
        if (displayUrl && dataUrl) {
            // Request screenshot for the display URL
            requestScreenshot(displayUrl, 1400, false)
        }
    }

    return (
        <div className="flex gap-2 justify-between">
            <LemonInput
                size="small"
                placeholder="Auto-generated from display URL above"
                value={dataUrl || ''}
                onChange={(value) => setDataUrl(value || null)}
                className="truncate flex-1"
                disabledReason={!displayUrl ? 'Set a valid Display URL first' : undefined}
            />

            {/* NEW: Load Heatmap Button */}
            <LemonButton
                type="primary"
                size="small"
                onClick={handleLoadHeatmap}
                loading={screenshotLoading}
                disabled={!displayUrl || !dataUrl || !isBrowserUrlValid}
                icon={<IconHeatmap />}
                data-attr="load-heatmap"
            >
                Load Heatmap
            </LemonButton>

            <ExportButton iframeRef={iframeRef} />
        </div>
    )
}
```

**Benefits of Manual Loading:**

- **Performance**: No automatic screenshot generation on URL change
- **Cost control**: Screenshots only generated when explicitly requested
- **User intent**: Clear indication when heatmap loading is initiated
- **Better UX**: Users understand when processing is happening
- **Bandwidth savings**: Avoid unnecessary screenshot requests
- **Resource efficiency**: Prevents accidental screenshot generation while typing

#### Loading States

- Show skeleton loader while screenshot is being generated
- Display progress indicator for long-running screenshots
- Provide estimated completion time
- Clear "Load Heatmap" button state management
- Progress indicator in button during loading

#### Error Handling

- Clear error messages for common failures
- Retry buttons for transient errors
- Fallback suggestions (try different URL, check website accessibility)
- Inline error display with retry option
- Error state management in "Load Heatmap" button

#### Caching Indicators

- Show when using cached screenshot
- Display cache age and expiry
- Option to force refresh via "Load Heatmap" button
- Visual indication of screenshot freshness
- Cache status in button tooltip

---

## Implementation Plan

### Phase 1: Backend

1. Create `HeatmapScreenshot` model and migration
2. Add screenshot API endpoints to `HeatmapViewSet`
3. Create `generate_heatmap_screenshot` Celery task

### Phase 2: Frontend

1. Add screenshot state to existing `heatmapsBrowserLogic`
2. Update `HeatmapsBrowser` component with "Load Heatmap" button
3. Replace iframe with screenshot display

### Phase 3: Deploy

1. Deploy with feature flag
2. Test and monitor
3. Full rollout

---

## Key Considerations

### Security

- URL validation blocks private IPs and non-HTTP(S) protocols
- Rate limiting: 50 requests/hour per team
- Team-based screenshot isolation

### Performance

- Screenshots cached and reused via `cache_key`
- Automatic cleanup of unused screenshots after 30 days
- Object storage for efficient image serving

### Monitoring

- Track screenshot success rates and generation times
- Monitor storage usage and cleanup effectiveness
