# PostHog Conversations Widget - Integration Guide

This document explains how to integrate the PostHog Conversations widget, including authentication, API endpoints, and security for both identified and anonymous users.

**Audience**: This guide is for posthog-js developers implementing the widget.

## Authentication Model

### Public Token (Team-level auth)

- `conversations_public_token` authenticates the **TEAM**, not the user
- Similar to PostHog's public ingestion token - it's meant to be embedded in client-side code
- Validates: "You're allowed to create tickets/messages for this team"
- **Scoping**: Token is read-only for widget operations, cannot access admin endpoints

### Session ID (Access Control) - **CRITICAL FOR SECURITY**

- `widget_session_id` is a **random UUID** generated client-side, stored in localStorage
- This is what controls **ACCESS** to tickets
- Widget can ONLY access tickets that match its own widget_session_id
- **Why not distinct_id?** Because distinct_id is often an email, which is guessable

### Distinct ID (Person Linking Only)

- `distinct_id` is PostHog's standard user identifier
- Used **ONLY** for linking conversations to Person records in PostHog
- **NOT used for access control** - someone knowing your email can't access your chats

## Flow for Different User Types

### Anonymous (Non-identified) Users

1. User opens widget on website
2. Widget generates random `widget_session_id` (e.g., `f47ac10b-58cc-4372-...`), stores in localStorage
3. posthog-js has anonymous `distinct_id` (e.g., `abc-123-uuid`)
4. Widget sends message with:
   - `conversations_public_token` (from Team config)
   - `widget_session_id`: `f47ac10b-58cc-4372-...` (random, for access control)
   - `distinct_id`: `abc-123-uuid` (for Person linking)
   - `traits`: `{name: null, email: null}` (empty)
5. Backend:
   - Validates token → gets team_id
   - Finds or creates `Ticket(team_id, widget_session_id="f47ac10b-...")`
   - Creates Comment linked to ticket
6. Widget polls for responses using same widget_session_id

### Identified Users

1. User logs in, website calls `posthog.identify('user@example.com')`
2. Widget sends message with:
   - `conversations_public_token`
   - `widget_session_id`: `f47ac10b-58cc-4372-...` (same as before - stays in localStorage)
   - `distinct_id`: `user@example.com` (for Person linking)
   - `traits`: `{name: "John", email: "user@example.com"}`
3. Backend:
   - Validates token → gets team_id
   - Finds ticket by `widget_session_id` (NOT distinct_id)
   - Updates `ticket.distinct_id` to new value (for Person linking)
   - Stores traits in `anonymous_traits` JSON
4. Widget polls using same `widget_session_id`

### Anonymous → Identified Transition

1. User starts anonymous: `widget_session_id="f47ac10b-..."`, `distinct_id="abc-123"`
2. Creates ticket, sends messages
3. User logs in, `posthog.identify('user@example.com')` is called
4. Widget uses **same widget_session_id** but new `distinct_id`
5. Backend updates `ticket.distinct_id` for Person linking
6. **User keeps access to their ticket** because widget_session_id hasn't changed

## Security Model

### What's Protected

```python
# Backend validation in api/widget.py

def post_message(request):
    # 1. Validate public token
    token = request.headers.get('X-Conversations-Token')
    team = Team.objects.get(conversations_public_token=token)  # or 401
    
    # 2. Get widget_session_id (access control) and distinct_id (Person linking)
    widget_session_id = request.data['widget_session_id']  # Random UUID from localStorage
    distinct_id = request.data['distinct_id']  # For Person linking only
    
    # 3. Scope ticket to (team, widget_session_id) - NOT distinct_id!
    ticket = Ticket.objects.filter(team=team, widget_session_id=widget_session_id).first()
    if not ticket:
        ticket = Ticket.objects.create(
            team=team,
            widget_session_id=widget_session_id,
            distinct_id=distinct_id,
            status='new'
        )
    
    # Widget can ONLY access tickets with matching widget_session_id
    # Knowing someone's email (distinct_id) does NOT grant access
```

### Security Rules

**Widget endpoints should:**

- ✅ Allow creating/reading tickets for provided widget_session_id
- ✅ Allow reading messages for tickets owned by widget_session_id
- ❌ NOT allow reading tickets from different widget_session_ids
- ❌ NOT allow access based on knowing distinct_id/email
- ❌ NOT allow admin operations (changing settings, seeing all tickets)
- ✅ Apply rate limiting per widget_session_id or IP

**Critical Validation:**

```python
def get_messages(request, ticket_id):
    token = request.headers.get('X-Conversations-Token')
    widget_session_id = request.GET.get('widget_session_id')  # NOT distinct_id!
    
    team = Team.objects.get(conversations_public_token=token)
    ticket = Ticket.objects.get(id=ticket_id, team=team)
    
    # CRITICAL: Verify the ticket belongs to this widget_session_id
    # This is a random UUID, impossible to guess
    if ticket.widget_session_id != widget_session_id:
        return 403  # Forbidden
    
    messages = Comment.objects.filter(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket_id)
    )
    return messages
```

## Security Best Practices

### Understanding the Security Model

**Important**: `conversations_public_token` is **meant to be public** (like PostHog's `phc_` token or Stripe's `pk_` key).

**Why this is safe:**

- Token only authenticates the TEAM, not individual users
- Real security comes from `widget_session_id` scoping on the backend
- `widget_session_id` is a random UUID stored in localStorage - impossible to guess
- `distinct_id` (email) is only used for Person linking, NOT access control
- Similar to how Crisp, Intercom, Zendesk, Drift widgets work
- Token is read-only for widget operations (no admin access)

**What an attacker with the token CAN do:**

- ❌ Create spam tickets (mitigated by rate limiting)
- ❌ Try to DoS via rate limits (mitigated by IP-based limits)

**What an attacker CANNOT do:**

- ✅ Access conversations from other widget_session_ids (random UUIDs are unguessable)
- ✅ Access someone's chats by knowing their email
- ✅ Access admin endpoints or settings
- ✅ See all team tickets
- ✅ Modify existing tickets (except those with their own widget_session_id)

### Rate Limiting (Critical)

The backend implements **multi-layer rate limiting**:

**Per widget_session_id limits:**

- Messages: 10 per minute, 50 per hour
- Message fetches: 30 per minute
- Ticket creation: 3 per hour (first-time widget_session_ids)

**Per IP limits:**

- Messages: 100 per minute (across all widget_session_ids)
- Prevents single attacker from creating many widget_session_ids

**Per team/token limits:**

- Total messages: 1000 per hour
- New tickets: 100 per hour
- Prevents token-based DoS

### Input Validation

All inputs are validated on the backend:

- Max message length: 5000 chars
- Max trait values: 500 chars each
- Session_id format validation (must be valid UUID)
- Distinct_id format validation (max 200 chars)
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

// Generate or retrieve widget_session_id (random UUID for access control)
function getOrCreateSessionId() {
  const STORAGE_KEY = 'ph_conversations_widget_session_id'
  let sessionId = localStorage.getItem(STORAGE_KEY)
  
  if (!sessionId) {
    sessionId = crypto.randomUUID()  // e.g., "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    localStorage.setItem(STORAGE_KEY, sessionId)
  }
  
  return sessionId
}

const widget = {
  greeting: config.conversations_greeting_text,
  color: config.conversations_color,
  publicToken: config.conversations_public_token,
  sessionId: getOrCreateSessionId(),  // Random UUID for ACCESS CONTROL
  distinctId: posthog.get_distinct_id(),  // For Person linking only
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

### POST /api/conversations/v1/widget/message

Create a new message or start a new conversation.

**Request:**

```json
{
  "widget_session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",  // REQUIRED: Random UUID for access control
  "distinct_id": "user@example.com",  // REQUIRED: For Person linking
  "message": "I need help with my billing",
  "traits": {
    "name": "John Doe",
    "email": "user@example.com",
    "company": "Acme Inc"
  },
  "ticket_id": null  // Optional: include to add to existing ticket
}
```

**Success Response (200):**

```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "message_id": "660e8400-e29b-41d4-a716-446655440001",
  "ticket_status": "new",
  "unread_count": 0,
  "created_at": "2024-01-01T12:00:00Z"
}
```

**Error Responses:**

- `401 Unauthorized`: Invalid or missing token
- `403 Forbidden`: Ticket exists but doesn't belong to this widget_session_id
- `429 Too Many Requests`: Rate limit exceeded
- `400 Bad Request`: Invalid message format, missing required fields, or invalid widget_session_id format

**Notes:**

- `widget_session_id` must be a valid UUID (generated client-side, stored in localStorage)
- First message creates a new ticket associated with the widget_session_id
- Subsequent messages should include `ticket_id`
- `distinct_id` can change (anonymous → identified) - backend updates ticket.distinct_id
- `traits` are stored in `Ticket.anonymous_traits` (merged on each message)
- Empty/null traits are allowed for anonymous users

### GET /api/conversations/v1/widget/messages/:ticket_id

Get all messages for a ticket.

**Query Parameters:**

```http
?widget_session_id=f47ac10b-58cc-4372-a567-0e02b2c3d479  // REQUIRED: for access control
&after=2024-01-01T12:00:00Z    // Optional: only get messages after this timestamp
&limit=50                       // Optional: default 100, max 500
```

**Success Response (200):**

```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "ticket_status": "open",
  "unread_count": 2,
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
- `403 Forbidden`: Ticket doesn't belong to this widget_session_id
- `404 Not Found`: Ticket doesn't exist
- `400 Bad Request`: Missing or invalid widget_session_id

**Notes:**

- Access controlled by widget_session_id (knowing the email doesn't grant access)
- Only returns messages where `is_private=false`
- Messages are ordered by `created_at` ascending (oldest first)
- Use `after` parameter for polling (every 5-10 seconds)

### GET /api/conversations/v1/widget/tickets

Get all tickets for current widget_session_id (browser session).

**Query Parameters:**

```http
?widget_session_id=f47ac10b-58cc-4372-a567-0e02b2c3d479  // REQUIRED: for access control
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
      "unread_count": 2,
      "last_message": "Sure, it's john@example.com",
      "last_message_at": "2024-01-01T12:00:15Z",
      "message_count": 3,
      "created_at": "2024-01-01T12:00:00Z"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440111",
      "status": "resolved",
      "unread_count": 0,
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
- `400 Bad Request`: Missing or invalid widget_session_id

**Notes:**

- Returns only tickets owned by this widget_session_id
- Different devices/browsers have different widget_session_ids, so chat history is per-browser
- This is by design for security - prevents accessing chats by knowing someone's email

### POST /api/conversations/v1/widget/messages/:ticket_id/read

Mark all messages in a ticket as read by the customer. Resets the unread counter to 0.

**Request:**

```json
{
  "widget_session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

**Success Response (200):**

```json
{
  "success": true,
  "unread_count": 0
}
```

**Error Responses:**

- `401 Unauthorized`: Invalid token
- `403 Forbidden`: Ticket doesn't belong to this widget_session_id
- `404 Not Found`: Ticket doesn't exist
- `400 Bad Request`: Missing or invalid widget_session_id

## Unread Message Counters

The widget tracks unread messages in both directions:

### How It Works

| Direction | Field | Incremented When | Reset When |
|-----------|-------|------------------|------------|
| Customer → Team | `unread_team_count` | Customer sends a message | Team member opens ticket in dashboard |
| Team → Customer | `unread_customer_count` | Team/AI sends a message | Customer calls mark-read endpoint |

### Widget Badge

The `unread_count` field is included in all responses:

- **POST /message** → `unread_count` (messages customer hasn't seen)
- **GET /messages** → `unread_count` (messages customer hasn't seen)
- **GET /tickets** → `unread_count` per ticket

Use this to show a badge on the widget button when there are unread replies.

### Typical Flow

```javascript
// 1. Widget opens - check for unread messages
const response = await fetch(`/api/conversations/v1/widget/tickets?widget_session_id=${sessionId}`)
const data = await response.json()

// Calculate total unread across all tickets
const totalUnread = data.results.reduce((sum, t) => sum + t.unread_count, 0)
if (totalUnread > 0) {
  showBadge(totalUnread)
}

// 2. User opens a conversation - mark as read
async function openConversation(ticketId) {
  // Get messages
  const messages = await fetchMessages(ticketId)
  
  // Mark as read
  await fetch(`/api/conversations/v1/widget/messages/${ticketId}/read`, {
    method: 'POST',
    headers: {
      'X-Conversations-Token': config.publicToken,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ widget_session_id: sessionId })
  })
  
  // Update badge
  updateBadge()
}

// 3. Polling - check for new messages
setInterval(async () => {
  const response = await fetchMessages(currentTicketId)
  if (response.unread_count > 0) {
    // New message from support!
    showNotification()
  }
}, 5000)
```

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
    widget_session_id: widget.sessionId,  // Random UUID from localStorage
    after: lastMessageTimestamp,
    limit: 50
  }
  
  const response = await fetch(
    `/api/conversations/v1/widget/messages/${currentTicketId}?${new URLSearchParams(params)}`,
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
    const response = await fetch('/api/conversations/v1/widget/message', {
      method: 'POST',
      headers: {
        'X-Conversations-Token': config.conversations_public_token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        widget_session_id: widget.sessionId,  // Random UUID from localStorage
        distinct_id: posthog.get_distinct_id(),  // For Person linking
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
// Session ID is stored separately - this is the key for access control
const SESSION_KEY = 'ph_conversations_widget_session_id'
const TICKET_KEY = 'ph_conversations_current_ticket'

function getOrCreateSessionId() {
  let sessionId = localStorage.getItem(SESSION_KEY)
  if (!sessionId) {
    sessionId = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, sessionId)
  }
  return sessionId
}

function saveTicketId(ticketId) {
  localStorage.setItem(TICKET_KEY, ticketId)
}

function loadTicketId() {
  return localStorage.getItem(TICKET_KEY)
}

// On widget open, check for existing ticket
async function initializeWidget() {
  const sessionId = getOrCreateSessionId()
  const savedTicketId = loadTicketId()
  
  if (savedTicketId) {
    // Verify ticket still exists and belongs to this session
    try {
      const response = await fetchMessages(savedTicketId, sessionId)
      if (response.ok) {
        currentTicketId = savedTicketId
        loadMessages(response.data.messages)
      } else {
        // Ticket doesn't exist or doesn't belong to this session
        localStorage.removeItem(TICKET_KEY)
      }
    } catch (error) {
      localStorage.removeItem(TICKET_KEY)
    }
  }
}
```

### Distinct ID Handling (Anonymous → Identified)

```javascript
// Handle anonymous -> identified transition
// IMPORTANT: widget_session_id stays the same, only distinct_id changes
posthog.on('identify', (newDistinctId) => {
  // Update widget's distinct_id reference
  widget.distinctId = newDistinctId
  
  // NO need to clear ticket or session!
  // Same widget_session_id means user keeps access to their conversation
  // Backend will update ticket.distinct_id for Person linking
  
  // Just update traits on next message
  console.log('User identified, distinct_id updated for Person linking')
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

- **Messages**: 10 per minute per widget_session_id
- **Polls**: 30 per minute per widget_session_id (don't poll faster than 2s)
- **Ticket creation**: 5 per hour per widget_session_id

When rate limited (429), exponentially back off:

1. First limit: wait 60 seconds
2. Second limit: wait 120 seconds
3. Third limit: wait 300 seconds

## Testing

### Test with cURL

```bash
# Get team config
curl https://app.posthog.com/api/projects/123/environments/456/

# Generate a random widget_session_id (UUID)
SESSION_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Send a message
curl -X POST https://app.posthog.com/api/conversations/v1/widget/message \
  -H "X-Conversations-Token: phc_abc123..." \
  -H "Content-Type: application/json" \
  -d "{
    \"widget_session_id\": \"$SESSION_ID\",
    \"distinct_id\": \"test-user-123\",
    \"message\": \"Test message\",
    \"traits\": {\"name\": \"Test User\"}
  }"

# Get messages (use same widget_session_id)
curl "https://app.posthog.com/api/conversations/v1/widget/messages/550e8400-e29b-41d4-a716-446655440000?widget_session_id=$SESSION_ID" \
  -H "X-Conversations-Token: phc_abc123..."
```

## Summary

- **Initialization**: Fetch team config to get `conversations_public_token` and settings
- **Public token** = Team auth (read-only widget operations) - meant to be public!
- **widget_session_id** = Random UUID for ACCESS CONTROL (stored in localStorage) - the REAL security boundary
- **distinct_id** = PostHog user ID for PERSON LINKING only - NOT used for access control
- **Anonymous → Identified**: widget_session_id stays same, distinct_id updates, user keeps access
- **Polling**: Poll messages endpoint every 5s when widget is open
- **Persistence**: Store widget_session_id and ticket_id in localStorage
- **Rate limiting**: Multi-layer (widget_session_id, IP, team) - most critical security control
- **Error handling**: Gracefully handle 401, 403, 429, 500 errors

### Why This Is Safe (Security Model)

**Token is public by design** (like PostHog's `phc_` key):

1. ✅ Token only authenticates the TEAM (like "which PostHog project is this?")
2. ✅ Real security comes from `widget_session_id` validation on every request
3. ✅ `widget_session_id` is a random UUID - impossible to guess (2^122 bits of entropy)
4. ✅ Knowing someone's email does NOT grant access to their chats
5. ✅ Widget can't do admin operations (token is widget-scoped only)

**Multi-layer protection:**
6. ✅ Rate limiting prevents spam/DoS (per widget_session_id, per IP, per team)
7. ✅ Origin validation prevents token reuse on attacker's domain
8. ✅ Input validation prevents injection attacks
9. ✅ Private messages (internal notes) are never returned to widget
10. ✅ Manual token rotation available for suspected compromise

**What matters most:**

- 🔐 **widget_session_id validation** - always check `ticket.widget_session_id == request.widget_session_id`
- 🔐 **widget_session_id is unguessable** - random UUID, not an email
- 🔐 **Rate limiting** - aggressive multi-layer limits
- 🔐 **Origin validation** - prevent token reuse from other domains

**Don't worry about:**

- ❌ Token being visible in client code (by design)
- ❌ Frequent token rotation (unnecessary and breaks UX)
- ❌ Someone seeing the token in network tab (expected)
- ❌ Someone knowing a user's email (doesn't grant access)
