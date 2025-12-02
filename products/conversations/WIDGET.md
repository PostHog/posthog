# PostHog Conversations Widget - Integration Guide

This document explains how to integrate the PostHog Conversations widget, including authentication, API endpoints, and security for both identified and anonymous users.

**Audience**: This guide is for posthog-js developers implementing the widget.

## Authentication Model

### Public Token (Team-level auth)

- `conversations_public_token` authenticates the **TEAM**, not the user
- Similar to PostHog's public ingestion token - it's meant to be embedded in client-side code
- Validates: "You're allowed to create tickets/messages for this team"
- **Scoping**: Token is read-only for widget operations, cannot access admin endpoints

### Distinct ID (User-level scoping)

- `distinct_id` is what scopes data to the **USER**
- This is PostHog's standard user identifier from posthog-js
- Widget can ONLY access tickets that match its own distinct_id

## Flow for Different User Types

### Anonymous (Non-identified) Users

1. User opens widget on website
2. posthog-js generates anonymous distinct_id (e.g., `abc-123-uuid`)
3. Widget sends message with:
   - `conversations_public_token` (from Team config)
   - `distinct_id`: `abc-123-uuid`
   - `traits`: `{name: null, email: null}` (empty)
4. Backend:
   - Validates token → gets team_id
   - Finds or creates `Ticket(team_id, distinct_id="abc-123-uuid")`
   - Creates Comment linked to ticket
5. Widget polls for responses using same distinct_id

### Identified Users

1. User logs in, website calls `posthog.identify('user@example.com')`
2. Widget sends message with:
   - `conversations_public_token`
   - `distinct_id`: `user@example.com`
   - `traits`: `{name: "John", email: "user@example.com"}`
3. Backend:
   - Validates token → gets team_id
   - Finds or creates `Ticket(team_id, distinct_id="user@example.com")`
   - Stores traits in `anonymous_traits` JSON
   - Can optionally link to Person model if exists
4. Widget polls using `distinct_id="user@example.com"`

### Anonymous → Identified Transition

1. User starts anonymous: `distinct_id="abc-123"`
2. Creates ticket, sends messages
3. User logs in, `posthog.alias()` is called
4. Widget now uses `distinct_id="user@example.com"`
5. Options:
   - **For MVP**: Create new ticket (simplest)
   - **Post-MVP**: Merge old ticket with new distinct_id

## Security Model

### What's Protected

```python
# Backend validation in api/widget.py

def post_message(request):
    # 1. Validate public token
    token = request.headers.get('X-Conversations-Token')
    team = Team.objects.get(conversations_public_token=token)  # or 401
    
    # 2. Get distinct_id from request body
    distinct_id = request.data['distinct_id']
    
    # 3. Scope ticket to (team, distinct_id)
    ticket, created = Ticket.objects.get_or_create(
        team=team,
        distinct_id=distinct_id,
        defaults={'status': 'new'}
    )
    
    # Widget can ONLY access this specific ticket
    # Cannot access other distinct_ids' tickets
```

### Security Rules

**Widget endpoints should:**

- ✅ Allow creating/reading tickets for provided distinct_id
- ✅ Allow reading messages for tickets owned by distinct_id
- ❌ NOT allow reading tickets from different distinct_ids
- ❌ NOT allow admin operations (changing settings, seeing all tickets)
- ✅ Apply rate limiting per distinct_id or IP

**Critical Validation:**

```python
def get_messages(request, ticket_id):
    token = request.headers.get('X-Conversations-Token')
    distinct_id = request.GET.get('distinct_id')
    
    team = Team.objects.get(conversations_public_token=token)
    ticket = Ticket.objects.get(id=ticket_id, team=team)
    
    # CRITICAL: Verify the ticket belongs to this distinct_id
    if ticket.distinct_id != distinct_id:
        return 403  # Forbidden
    
    messages = Comment.objects.filter(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket_id)
    )
    return messages
```

## Security Best Practices

### Understanding the Token Model

**Important**: `conversations_public_token` is **meant to be public** (like PostHog's `phc_` token or Stripe's `pk_` key).

**Why this is safe:**

- Token only authenticates the TEAM, not individual users
- Real security comes from `distinct_id` scoping on the backend
- Similar to how Intercom, Zendesk, Drift widgets work
- Token is read-only for widget operations (no admin access)

**What an attacker with the token CAN do:**

- ❌ Create spam tickets (mitigated by rate limiting)
- ❌ Try to DoS via rate limits (mitigated by IP-based limits)

**What an attacker CANNOT do:**

- ✅ Access conversations from other distinct_ids
- ✅ Access admin endpoints or settings
- ✅ See all team tickets
- ✅ Modify existing tickets (except those with their own distinct_id)

### Rate Limiting (Critical)

The backend implements **multi-layer rate limiting**:

**Per distinct_id limits:**

- Messages: 10 per minute, 50 per hour
- Message fetches: 30 per minute
- Ticket creation: 3 per hour (first-time distinct_ids)

**Per IP limits:**

- Messages: 100 per minute (across all distinct_ids)
- Prevents single attacker from creating many distinct_ids

**Per team/token limits:**

- Total messages: 1000 per hour
- New tickets: 100 per hour
- Prevents token-based DoS

### Input Validation

All inputs are validated on the backend:

- Max message length: 5000 chars
- Max trait values: 500 chars each
- Distinct_id format validation (alphanumeric, dashes, underscores, max 200 chars)
- HTML/script sanitization in message content
- Rejection of suspicious patterns

### Token Rotation (Manual)

**Do NOT rotate automatically** - would break all active sessions.

**Manual rotation available** when suspected compromise:

- API endpoint: `POST /api/projects/:id/environments/:team_id/generate_conversations_public_token`
- Old token immediately invalid
- Team must update their website with new token

**When to rotate:**

- Suspected token leak or misuse
- Excessive spam/abuse detected
- On request from security team
- After revoking team member access

### Origin Validation

Backend validates the `Origin` or `Referer` header against team's allowed domains. This prevents token reuse on attacker's websites.

## Widget Initialization Flow

### 1. Get Widget Configuration

The widget needs to fetch configuration from the Team API before it can function.

**Endpoint**: `GET /api/projects/:project_id/environments/:team_id/`

**Response includes:**

```json
{
  "id": 12345,
  "conversations_enabled": true,
  "conversations_greeting_text": "Hi! How can we help?",
  "conversations_color": "#5375ff",
  "conversations_public_token": "phc_abc123def456..."
}
```

**Widget should:**

1. Check `conversations_enabled` - don't show widget if false
2. Use `conversations_greeting_text` for initial message
3. Use `conversations_color` for widget styling
4. Store `conversations_public_token` for all subsequent API calls

### 2. Initialize Widget State

```javascript
// Pseudocode for widget initialization
const config = await fetchTeamConfig()

if (!config.conversations_enabled) {
  return // Don't render widget
}

const widget = {
  greeting: config.conversations_greeting_text,
  color: config.conversations_color,
  publicToken: config.conversations_public_token,
  distinctId: posthog.get_distinct_id(),
  currentTicketId: null // Will be set after first message
}
```

## Widget API Endpoints

All widget endpoints use a custom authentication mechanism (NOT standard PostHog auth).

### Common Request Headers

```http
X-Conversations-Token: <conversations_public_token>
Content-Type: application/json
```

### POST /api/conversations/widget/message

Create a new message or start a new conversation.

**Request:**

```json
{
  "distinct_id": "user@example.com",
  "message": "I need help with my billing",
  "traits": {
    "name": "John Doe",
    "email": "user@example.com",
    "company": "Acme Inc"
  },
  "ticket_id": null  // Optional: include to add to existing ticket
}
```

**Success Response (201):**

```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "message_id": "660e8400-e29b-41d4-a716-446655440001",
  "ticket_status": "new",
  "created_at": "2024-01-01T12:00:00Z"
}
```

**Error Responses:**

- `401 Unauthorized`: Invalid or missing token
- `403 Forbidden`: Ticket exists but doesn't belong to this distinct_id
- `429 Too Many Requests`: Rate limit exceeded
- `400 Bad Request`: Invalid message format or missing required fields

**Notes:**

- First message creates a new ticket
- Subsequent messages should include `ticket_id`
- `traits` are stored in `Ticket.anonymous_traits` (replaces existing traits on each message)
- Empty/null traits are allowed for anonymous users

### GET /api/conversations/widget/messages/:ticket_id

Get all messages for a ticket.

**Query Parameters:**

```http
?distinct_id=user@example.com  // REQUIRED
&after=2024-01-01T12:00:00Z    // Optional: only get messages after this timestamp
&limit=50                       // Optional: default 100, max 500
```

**Success Response (200):**

```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "ticket_status": "open",
  "messages": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "content": "I need help with my billing",
      "author_type": "customer",
      "author_name": "John Doe",
      "created_at": "2024-01-01T12:00:00Z",
      "is_private": false
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440002",
      "content": "I'll help you with that. Can you provide your account email?",
      "author_type": "AI",
      "author_name": "PostHog Assistant",
      "created_at": "2024-01-01T12:00:05Z",
      "is_private": false
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440003",
      "content": "Sure, it's john@example.com",
      "author_type": "customer",
      "author_name": "John Doe",
      "created_at": "2024-01-01T12:00:15Z",
      "is_private": false
    }
  ],
  "has_more": false
}
```

**Message Fields:**

- `id`: Unique message ID (Comment.id)
- `content`: Message text
- `author_type`: `"customer"` | `"AI"` | `"human"` (from `item_context.author_type`)
- `author_name`: Display name (from `created_by` or traits)
- `created_at`: ISO timestamp
- `is_private`: Internal notes are not returned to widget (filtered server-side)

**Error Responses:**

- `401 Unauthorized`: Invalid token
- `403 Forbidden`: Ticket doesn't belong to this distinct_id
- `404 Not Found`: Ticket doesn't exist

**Notes:**

- Only returns messages where `is_private=false`
- Messages are ordered by `created_at` ascending (oldest first)
- Use `after` parameter for polling (every 5-10 seconds)

### GET /api/conversations/widget/tickets

Get all tickets for current distinct_id.

**Query Parameters:**

```http
?distinct_id=user@example.com  // REQUIRED
&status=open                   // Optional: filter by status
&limit=10                       // Optional: default 10, max 50
&offset=0                       // Optional: for pagination
```

**Success Response (200):**

```json
{
  "count": 2,
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "open",
      "last_message": "Sure, it's john@example.com",
      "last_message_at": "2024-01-01T12:00:15Z",
      "message_count": 3,
      "created_at": "2024-01-01T12:00:00Z"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440111",
      "status": "resolved",
      "last_message": "Thank you for your help!",
      "last_message_at": "2023-12-28T14:30:00Z",
      "message_count": 8,
      "created_at": "2023-12-28T14:00:00Z"
    }
  ]
}
```

**Ticket Statuses:**

- `new`: Just created, no human/AI response yet
- `open`: Active conversation
- `pending`: Waiting for customer response
- `on_hold`: Paused by support team
- `resolved`: Conversation closed

**Error Responses:**

- `401 Unauthorized`: Invalid token
- `400 Bad Request`: Missing distinct_id

## Implementation Recommendations

### Polling Strategy

For live updates, poll the messages endpoint:

```javascript
let lastMessageTimestamp = null
let currentTicketId = null

// Poll every 5 seconds when widget is open
setInterval(async () => {
  if (!currentTicketId) return
  
  const params = {
    distinct_id: posthog.get_distinct_id(),
    after: lastMessageTimestamp,
    limit: 50
  }
  
  const response = await fetch(
    `/api/conversations/widget/messages/${currentTicketId}?${new URLSearchParams(params)}`,
    {
      headers: {
        'X-Conversations-Token': config.conversations_public_token
      }
    }
  )
  
  const data = await response.json()
  
  if (data.messages.length > 0) {
    // Update UI with new messages
    appendMessages(data.messages)
    lastMessageTimestamp = data.messages[data.messages.length - 1].created_at
  }
  
  // Update ticket status if changed
  if (data.ticket_status !== currentTicketStatus) {
    updateTicketStatus(data.ticket_status)
  }
}, 5000)
```

### Error Handling

```javascript
async function sendMessage(message) {
  try {
    const response = await fetch('/api/conversations/widget/message', {
      method: 'POST',
      headers: {
        'X-Conversations-Token': config.conversations_public_token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        distinct_id: posthog.get_distinct_id(),
        message: message,
        traits: {
          name: getUserName(),
          email: getUserEmail()
        },
        ticket_id: currentTicketId
      })
    })
    
    if (response.status === 429) {
      showError('Too many messages. Please wait a moment.')
      return
    }
    
    if (response.status === 401) {
      showError('Widget is not properly configured.')
      return
    }
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    
    const data = await response.json()
    currentTicketId = data.ticket_id
    
    // Immediately poll for AI response
    setTimeout(() => pollForNewMessages(), 1000)
    
  } catch (error) {
    console.error('Failed to send message:', error)
    showError('Failed to send message. Please try again.')
  }
}
```

### Local Storage Persistence

```javascript
// Save current ticket ID to localStorage
// So user can resume conversation after page reload
const STORAGE_KEY = `ph_conversations_ticket_${posthog.get_distinct_id()}`

function saveTicketId(ticketId) {
  localStorage.setItem(STORAGE_KEY, ticketId)
}

function loadTicketId() {
  return localStorage.getItem(STORAGE_KEY)
}

// On widget open, check for existing ticket
async function initializeWidget() {
  const savedTicketId = loadTicketId()
  
  if (savedTicketId) {
    // Verify ticket still exists and belongs to this user
    try {
      const response = await fetchMessages(savedTicketId)
      if (response.ok) {
        currentTicketId = savedTicketId
        loadMessages(response.data.messages)
      } else {
        // Ticket doesn't exist or doesn't belong to user
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch (error) {
      localStorage.removeItem(STORAGE_KEY)
    }
  }
}
```

### Distinct ID Handling

```javascript
// Handle anonymous -> identified transition
posthog.on('identify', (newDistinctId) => {
  // Clear old ticket from localStorage
  const oldKey = `ph_conversations_ticket_${posthog.get_distinct_id()}`
  localStorage.removeItem(oldKey)
  
  // Reset widget state
  currentTicketId = null
  clearMessages()
  
  // Check for existing tickets with new distinct_id
  loadExistingTickets(newDistinctId)
})

// Update traits on every message
function getCurrentTraits() {
  const person = posthog.get_person_properties()
  
  return {
    name: person?.name || null,
    email: person?.email || null,
    // Add any other relevant traits
  }
}
```

## Rate Limits

Expected rate limits (subject to change):

- **Messages**: 10 per minute per distinct_id
- **Polls**: 30 per minute per distinct_id (don't poll faster than 2s)
- **Ticket creation**: 5 per hour per distinct_id

When rate limited (429), exponentially back off:

1. First limit: wait 60 seconds
2. Second limit: wait 120 seconds
3. Third limit: wait 300 seconds

## Testing

### Test with cURL

```bash
# Get team config
curl https://app.posthog.com/api/projects/123/environments/456/

# Send a message
curl -X POST https://app.posthog.com/api/conversations/widget/message \
  -H "X-Conversations-Token: phc_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "distinct_id": "test-user-123",
    "message": "Test message",
    "traits": {"name": "Test User"}
  }'

# Get messages
curl "https://app.posthog.com/api/conversations/widget/messages/550e8400-e29b-41d4-a716-446655440000?distinct_id=test-user-123" \
  -H "X-Conversations-Token: phc_abc123..."
```

## Summary

- **Initialization**: Fetch team config to get `conversations_public_token` and settings
- **Public token** = Team auth (read-only widget operations) - meant to be public!
- **distinct_id** = User scoping (can only see own tickets) - the REAL security boundary
- **No difference** between identified/anonymous for auth - both use distinct_id
- **Polling**: Poll messages endpoint every 5s when widget is open
- **Persistence**: Store ticket_id in localStorage for session continuity
- **Rate limiting**: Multi-layer (distinct_id, IP, team) - most critical security control
- **Error handling**: Gracefully handle 401, 403, 429, 500 errors

### Why This Is Safe (Security Model)

**Token is public by design** (like PostHog's `phc_` key):

1. ✅ Token only authenticates the TEAM (like "which PostHog project is this?")
2. ✅ Real security comes from `distinct_id` validation on every request
3. ✅ Widget can't access other users' tickets (distinct_id scoping enforced server-side)
4. ✅ Widget can't do admin operations (token is widget-scoped only)

**Multi-layer protection:**
5. ✅ Rate limiting prevents spam/DoS (per distinct_id, per IP, per team)
6. ✅ Origin validation prevents token reuse on attacker's domain
7. ✅ Input validation prevents injection attacks
8. ✅ Private messages (internal notes) are never returned to widget
9. ✅ Suspicious activity detection and auto-blocking
10. ✅ Manual token rotation available for suspected compromise

**What matters most:**

- 🔐 **distinct_id validation** - always check `ticket.distinct_id == request.distinct_id`
- 🔐 **Rate limiting** - aggressive multi-layer limits
- 🔐 **Origin validation** - prevent token reuse from other domains

**Don't worry about:**

- ❌ Token being visible in client code (by design)
- ❌ Frequent token rotation (unnecessary and breaks UX)
- ❌ Someone seeing the token in network tab (expected)
