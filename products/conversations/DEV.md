# Conversations Backend Development Guide

This document outlines the steps to build the backend for the Conversations product, following PostHog's architecture patterns.

## V1 MVP Scope

Absolute minimum to get it working:

- **Widget only** - Single channel (embeddable web widget implemented in posthog-js)
- No Slack, no email
- All knowledge articles apply to all conversations
- Core ticket + message CRUD
- Basic AI integration
- Skip: tests, activity logging, optimization, telemetry (add later)

## 1. Setup Django app structure ✅

**Status: COMPLETE**

Created core Django app files and registered the app:

- ✅ **apps.py**: Created `ConversationsConfig(AppConfig)` with `name = "products.conversations.backend"` and `label = "conversations"`
- ✅ **Register in settings**: Added `"products.conversations.backend.apps.ConversationsConfig"` to `PRODUCTS_APPS` in `posthog/settings/web.py`
- ✅ **Register in tach.toml**: Added new module block for conversations product

## 2. Design and create models ✅

**Status: COMPLETE**

Defined Django models for the core domain entities in `models/` directory:

### Core models implemented:

- **Channel**: ✅ Shared constants (`models/constants.py`)
  - Defines available channels: WIDGET, EMAIL, SLACK
  - Used across Ticket, ContentArticle, and GuidanceRule models

- **Ticket**: ✅ Main entity with status and channel metadata (`models/ticket.py`)
  - Identity: id, team, channel_source (Channel choices, default: WIDGET), distinct_id (customer identifier), created_at, updated_at
  - State: status (new/open/pending/on_hold/resolved) - default: new
    - Flow: New → Open → Pending → Resolved
    - On hold can be set at any time
  - Customer: anonymous_traits JSON (name, email, any traits from widget)
  - AI metadata: ai_resolved (boolean), escalation_reason
  - Indexes: (team_id, distinct_id), (team_id, status)
  - Skip for MVP: priority, SLA, owner, queue, person FK, detailed AI metadata, tracking timestamps
  
- **Messages**: Use existing `Comment` model (no new model needed)
  - Set `scope = "conversations_ticket"` and `item_id = str(ticket.id)` to link to tickets
  - Use `item_context` JSON field to store: `is_private`, `author_type` (customer/AI/human), channel metadata
  - Use `source_comment` FK for threading/replies
  - Use `rich_content` JSON for rich text formatting
  - Already has: team scoping, created_by, timestamps, soft deletion
  - Query messages: `Comment.objects.filter(team=team, scope="conversations_ticket", item_id=str(ticket_id))`

- **ContentArticle**: ✅ Knowledge base articles (WHAT the AI knows) (`models/content_article.py`)
  - Fields: title, body, team, is_enabled (on/off toggle)
  - channels: ArrayField of Channel choices (empty = all channels)
  - embeddings: JSONField storing vector embeddings for RAG semantic search
  - created_by: ForeignKey to User (who created the article)
  - Skipped for MVP: published_state, versioning, audience_scoping

- **GuidanceRule**: ✅ Behavioral rules (HOW the AI behaves) (`models/guidance_rule.py`)
  - Fields: team, rule_type (tone/escalation), name, content, is_active
  - channels: ArrayField of Channel choices (empty = all channels)
  - created_by: ForeignKey to User (who created the rule)
  - Skipped for MVP: conditions JSON, priority, destinations, triggers, rollout percentage

- **Widget settings**: ✅ Stored on Team model (no separate model needed)
  - ✅ Added fields to Team model: `conversations_enabled`, `conversations_greeting_text`, `conversations_color`, `conversations_public_token`
  - ✅ Follows session replay settings or survey settings pattern
  - 📝 Token generation method will be added when implementing Team API updates

### Model best practices:

- Use `UUIDTModel` base class for UUID primary keys
- Foreign keys: `models.ForeignKey("posthog.Team", on_delete=models.CASCADE)`
- Add indexes: (team_id, distinct_id), (team_id, status)
- Use `models.TextChoices` for status enum

## 3. Create and run migrations ✅

**Status: COMPLETE**

Generated and ran migrations for the models:

```bash
# First, add widget settings fields to Team model in posthog/models/team/team.py
python manage.py makemigrations posthog -n add_conversations_settings_to_team

# Then, create conversations product models
python manage.py makemigrations conversations -n initial_migration

# Run migrations
python manage.py migrate
```

✅ Migrations created and applied successfully
✅ `max_migration.txt` file created in `migrations/` directory with the latest migration number

## 4. Build API layer ✅

**Status: COMPLETE**

Created REST API endpoints in `api/` directory using DRF viewsets:

### API structure implemented:

- **api/tickets.py**: ✅ `TicketViewSet` - Basic CRUD for tickets
  - List with filters: status, distinct_id search
  - Annotations: message_count, last_message_at
  - Search by customer name/email in anonymous_traits
  - Ordered by created_at (newest first)
- **api/content.py**: ✅ `ContentArticleViewSet` - Manage knowledge base articles
  - Basic CRUD, filter by is_enabled
  - Search by title
  - Automatically sets created_by to current user
- **api/guidance.py**: ✅ `GuidanceRuleViewSet` - Manage AI behavioral rules
  - Basic CRUD, filter by is_active, rule_type
  - Search by name
  - Automatically sets created_by to current user
- **Team settings API**: ✅ Widget configuration stored on Team model
  - Added conversations settings to TEAM_CONFIG_FIELDS
  - Added action: `POST /api/environments/{id}/generate_conversations_public_token/`
- **api/widget.py**: 📝 Widget webhook endpoints (Step 7)
  - Public endpoints (authenticated by public_token)

Messages use the existing `Comment` API - filter by `scope="conversations_ticket"` and `item_id=ticket_id`.

### Implementation notes:

- ✅ All viewsets inherit from `TeamAndOrgViewSetMixin` for automatic team scoping
- ✅ Serializers include computed fields (message_count, last_message_at)
- ✅ Basic filtering and search implemented
- ✅ `created_by` automatically set to current user for content/guidance
- ✅ Uses `UserBasicSerializer` for user references

### API best practices:

- Inherit from `TeamAndOrgViewSetMixin` for automatic team scoping
- Use serializers for validation
- Implement `safely_get_queryset()` to filter by team_id
- Apply `IsAuthenticated` permission class

## 5. Update Team API for conversations settings ✅

**Status: COMPLETE**

Updated Team API to include conversations settings and token generation:

### Changes Made:

1. **Added to `TEAM_CONFIG_FIELDS`** in `posthog/api/team.py`:
   - `conversations_enabled`
   - `conversations_greeting_text`
   - `conversations_color`
   - `conversations_public_token`

2. **Added `conversations_public_token` to read_only_fields** in `TeamSerializer`:
   - Token can only be generated/regenerated via the action endpoint

3. **Added method to Team model** (`posthog/models/team/team.py`):
   - `generate_conversations_public_token_and_save()` - Generates/regenerates token with activity logging

4. **Added action to TeamViewSet** (`posthog/api/team.py`):
   - `POST /api/environments/{id}/generate_conversations_public_token/`
   - Requires ADMIN or higher permissions
   - Returns updated team with new token

## 6. Register API routes ✅

**Status: COMPLETE**

Registered API routes in `posthog/api/__init__.py`:

### Routes registered:

- ✅ `POST/GET/PATCH/DELETE /api/projects/{project_id}/environments/{team_id}/conversations/tickets/`
- ✅ `POST/GET/PATCH/DELETE /api/projects/{project_id}/environments/{team_id}/conversations/content/`
- ✅ `POST/GET/PATCH/DELETE /api/projects/{project_id}/environments/{team_id}/conversations/guidance/`

All viewsets are nested under `projects_router` with `team_id` scoping.

## 7. Add widget integration ✅

**Status: COMPLETE**

Created widget API endpoints with comprehensive security measures in `api/widget.py`.

### Authentication

Create custom authentication class for widget endpoints:

```python
# api/widget.py
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from posthog.models import Team

class WidgetAuthentication(BaseAuthentication):
    """Authenticate via conversations_public_token"""
    
    def authenticate(self, request):
        token = request.headers.get('X-Conversations-Token')
        if not token:
            raise AuthenticationFailed('Token required')
        
        try:
            team = Team.objects.get(
                conversations_public_token=token,
                conversations_enabled=True
            )
        except Team.DoesNotExist:
            raise AuthenticationFailed('Invalid token')
        
        # Set team on request for later use
        return (None, team)  # No user, just team
```

### POST /api/conversations/widget/message

Incoming message from widget:

```python
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from posthog.models.comment import Comment
from products.conversations.backend.models import Ticket

class WidgetMessageView(APIView):
    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]  # Token is sufficient
    
    def post(self, request):
        team = request.auth  # Set by authentication
        distinct_id = request.data.get('distinct_id')
        
        if not distinct_id:
            return Response({'error': 'distinct_id required'}, status=400)
        
        # Find or create ticket scoped to (team, distinct_id)
        ticket, created = Ticket.objects.get_or_create(
            team=team,
            distinct_id=distinct_id,
            defaults={
                'channel_source': 'widget',
                'status': 'new',
                'anonymous_traits': request.data.get('traits', {})
            }
        )
        
        # Update traits if ticket exists
        if not created and request.data.get('traits'):
            ticket.anonymous_traits.update(request.data['traits'])
            ticket.save(update_fields=['anonymous_traits', 'updated_at'])
        
        # Create message
        comment = Comment.objects.create(
            team=team,
            scope='conversations_ticket',
            item_id=str(ticket.id),
            content=request.data.get('message', ''),
            item_context={
                'author_type': 'customer',
                'distinct_id': distinct_id
            }
        )
        
        return Response({
            'ticket_id': str(ticket.id),
            'message_id': str(comment.id)
        })
```

### GET /api/conversations/widget/messages/:ticket_id

Fetch messages for widget:

```python
class WidgetMessagesView(APIView):
    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    
    def get(self, request, ticket_id):
        team = request.auth
        distinct_id = request.query_params.get('distinct_id')
        
        if not distinct_id:
            return Response({'error': 'distinct_id required'}, status=400)
        
        # Get ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id, team=team)
        except Ticket.DoesNotExist:
            return Response({'error': 'Ticket not found'}, status=404)
        
        # CRITICAL: Verify the ticket belongs to this distinct_id
        if ticket.distinct_id != distinct_id:
            return Response({'error': 'Forbidden'}, status=403)
        
        # Get messages
        messages = Comment.objects.filter(
            team=team,
            scope='conversations_ticket',
            item_id=str(ticket_id),
            deleted=False
        ).order_by('created_at')
        
        return Response({
            'messages': [
                {
                    'id': str(m.id),
                    'content': m.content,
                    'author_type': m.item_context.get('author_type', 'customer'),
                    'created_at': m.created_at.isoformat()
                }
                for m in messages
            ]
        })
```

### URL Configuration

Register widget endpoints:

```python
# In posthog/api/__init__.py or dedicated widget urls
from products.conversations.backend.api.widget import WidgetMessageView, WidgetMessagesView

urlpatterns = [
    path('api/conversations/widget/message', WidgetMessageView.as_view()),
    path('api/conversations/widget/messages/<uuid:ticket_id>', WidgetMessagesView.as_view()),
]
```

### Security Implementation

#### 1. Multi-layer Rate Limiting

Implement rate limiting using `django-ratelimit`:

```python
from django_ratelimit.decorators import ratelimit
from django.core.cache import cache

class WidgetMessageView(APIView):
    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    
    @ratelimit(key='user_or_ip', rate='10/m', method='POST')  # Per distinct_id or IP
    @ratelimit(key='header:x-conversations-token', rate='1000/h', method='POST')  # Per team
    def post(self, request):
        # Check if rate limited
        if getattr(request, 'limited', False):
            return Response(
                {'error': 'Rate limit exceeded. Please try again later.'},
                status=429
            )
        # ... rest of implementation
```

**Rate limit tiers:**

- **Per distinct_id**: 10 messages/min, 50 messages/hour
- **Per IP**: 100 messages/min (prevents distinct_id spam)
- **Per team/token**: 1000 messages/hour, 100 new tickets/hour

#### 2. Input Validation

Add validation helpers:

```python
import re
from rest_framework.exceptions import ValidationError

def validate_distinct_id(distinct_id):
    """Validate distinct_id format and entropy"""
    if not distinct_id or len(distinct_id) > 200:
        raise ValidationError('Invalid distinct_id length')
    
    # Reject low-entropy sequential IDs
    if re.match(r'^(user|test|temp)\d+$', distinct_id):
        raise ValidationError('Suspicious distinct_id pattern')
    
    # Require minimum length for anonymous IDs
    if len(distinct_id) < 16 and not '@' in distinct_id:
        raise ValidationError('distinct_id too short')
    
    return True

def sanitize_message_content(content):
    """Sanitize message content"""
    if len(content) > 5000:
        raise ValidationError('Message too long (max 5000 chars)')
    
    # Strip HTML for MVP (or use bleach library for allowlist)
    import html
    return html.escape(content)

def validate_traits(traits):
    """Validate customer traits"""
    if not isinstance(traits, dict):
        raise ValidationError('Traits must be a dictionary')
    
    for key, value in traits.items():
        if isinstance(value, str) and len(value) > 500:
            raise ValidationError(f'Trait value too long: {key}')
    
    return traits
```

Use in views:

```python
def post(self, request):
    team = request.auth
    distinct_id = request.data.get('distinct_id')
    
    # Validate
    validate_distinct_id(distinct_id)
    content = sanitize_message_content(request.data.get('message', ''))
    traits = validate_traits(request.data.get('traits', {}))
    
    # ... rest of implementation
```

#### 3. Origin Validation

Validate request origin to prevent token reuse:

```python
def validate_origin(request, team):
    """Check if request comes from allowed domain"""
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    
    if not origin:
        # Allow for mobile apps or non-browser clients
        # Could make this stricter later
        return True
    
    # Future: team.allowed_widget_domains field
    # For MVP, allow all origins but log suspicious ones
    # allowed_domains = team.allowed_widget_domains or []
    # if allowed_domains and not any(origin.startswith(d) for d in allowed_domains):
    #     return False
    
    return True

class WidgetMessageView(APIView):
    def post(self, request):
        team = request.auth
        
        if not validate_origin(request, team):
            return Response(
                {'error': 'Origin not allowed'},
                status=403
            )
        # ... rest
```

#### 4. Suspicious Activity Detection

Add monitoring for abuse patterns:

```python
from django.core.cache import cache

def check_suspicious_activity(team, distinct_id, content):
    """Detect and flag suspicious patterns"""
    cache_key_prefix = f'conversations:suspicious:{team.id}'
    
    # Track distinct_id creation rate per IP
    ip = get_client_ip(request)
    distinct_ids_key = f'{cache_key_prefix}:ip:{ip}:distinct_ids'
    distinct_ids = cache.get(distinct_ids_key, set())
    distinct_ids.add(distinct_id)
    cache.set(distinct_ids_key, distinct_ids, timeout=3600)
    
    if len(distinct_ids) > 10:
        # Log to monitoring system
        logger.warning(f'Suspicious: IP {ip} created {len(distinct_ids)} distinct_ids')
        return True
    
    # Check for spam content (same message across distinct_ids)
    content_hash = hashlib.md5(content.encode()).hexdigest()
    spam_key = f'{cache_key_prefix}:content:{content_hash}'
    spam_count = cache.get(spam_key, 0)
    cache.set(spam_key, spam_count + 1, timeout=3600)
    
    if spam_count > 5:
        logger.warning(f'Suspicious: Same message sent {spam_count} times')
        return True
    
    return False
```

#### 5. Honeypot Protection

Add honeypot field to detect bots:

```python
class WidgetMessageView(APIView):
    def post(self, request):
        # Check honeypot field (should be empty)
        if request.data.get('_hp'):
            # Bot filled the honeypot
            logger.warning(f'Bot detected via honeypot')
            return Response({'error': 'Invalid request'}, status=400)
        
        # ... rest of implementation
```

#### 6. Token Rotation Implementation

Already implemented in Step 5 via Team API:

```python
# POST /api/environments/{id}/generate_conversations_public_token/
# Implemented in posthog/api/team.py
```

#### 7. CORS Configuration

Configure CORS for widget endpoints:

```python
# In settings or middleware
CORS_ALLOW_WIDGET_ORIGINS = True  # Allow cross-origin for widget endpoints

# Or use django-cors-headers with specific patterns:
CORS_URLS_REGEX = r'^/api/conversations/widget/.*$'
```

### Widget API Contract

Coordinate with posthog-js team:

- **Widget sends**: `X-Conversations-Token` header, distinct_id, message content, customer traits (name, email)
- **Backend returns**: ticket_id, message_id, ticket_status
- **Widget polls**: GET endpoint every 5s for AI/human responses
- **Widget config**: Fetches settings from Team API (conversations_enabled, conversations_greeting_text, conversations_color, conversations_public_token)
- **Authentication**: Public token (team-level) + distinct_id (user-level scoping)
- **Security**: Multi-layer rate limiting, input validation, origin validation, suspicious activity detection

See **WIDGET.md** for complete API contract and integration guide for posthog-js developers.

### Implementation Summary

✅ **Authentication**:

- Created `WidgetAuthentication` class that validates `X-Conversations-Token` header
- Returns team object (no user) for widget requests
- Checks `conversations_enabled` flag

✅ **Endpoints Implemented**:

1. `POST /api/conversations/widget/message` - Create message and ticket
2. `GET /api/conversations/widget/messages/:ticket_id` - Fetch messages for a ticket
3. `GET /api/conversations/widget/tickets` - List all tickets for distinct_id

✅ **Security Measures**:

- **Multi-layer rate limiting** using `django-ratelimit`:
  - Per distinct_id: 10 messages/min
  - Per IP: 100 messages/min (prevents distinct_id spam)
  - Per team: 1000 messages/hour
- **Input validation**:
  - `validate_distinct_id()` - format and entropy checks
  - `sanitize_message_content()` - HTML escaping, length limits
  - `validate_traits()` - type and length validation
- **Origin validation** - `validate_origin()` checks request origin
- **Suspicious activity detection** - `check_suspicious_activity()` flags patterns
- **Honeypot protection** - `_hp` field to detect bots
- **distinct_id scoping** - Always verifies ticket.distinct_id matches request

✅ **Critical Security Pattern**:

```python
# ALWAYS verify ticket belongs to distinct_id
if ticket.distinct_id != distinct_id:
    return Response({'error': 'Forbidden'}, status=403)
```

✅ **URL Registration**:

- Created `api/urls.py` with widget URL patterns
- Registered in `posthog/urls.py` at `/api/conversations/`

✅ **Exports**:

- Added widget views to `api/__init__.py` exports

## Development workflow

1. ✅ Add widget settings fields to Team model (conversations_enabled, conversations_greeting_text, conversations_color, conversations_public_token) and create migration
2. ✅ Implement core models (Ticket, ContentArticle, GuidanceRule) and migrations
3. ✅ Run migrations
4. ✅ Build basic CRUD API for tickets (messages use existing Comment API)
5. ✅ Update Team API to include conversations settings and token generation
6. ✅ Register API routes
7. ✅ Implement widget webhook endpoints (POST message, GET messages, GET tickets) with comprehensive security
8. 🔄 Manual testing via curl/Postman
9. 🔄 Coordinate with posthog-js team for widget implementation and API contract

**Add later (post-MVP):**

- Tests (unit, API, integration)
- Activity logging for audit trail
- Performance optimization (indexes, select_related, prefetch_related)
- Telemetry and analytics tracking
- TicketAssignment model and assignment logic

## Key files to reference

Study these existing patterns:

- **links**: Simple CRUD example with team scoping (best starting point)
- **error_tracking**: Complex API with viewsets, filtering, issue management
- **Team model settings**: Look at existing session replay or survey settings in `posthog/models/team/team.py` for how to add conversations settings
- **WIDGET.md**: Detailed widget authentication and security documentation

## Common patterns

- **Team scoping**: Always filter by `team_id` in `safely_get_queryset()`
- **String relations**: Use `"posthog.Team"` for ForeignKeys to avoid circular imports
- **Error handling**: Use try-except blocks, return clear error messages
