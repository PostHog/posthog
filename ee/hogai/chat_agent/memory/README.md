# PostHog AI Chat Agent Memory System

The PostHog AI chat agent uses a dual memory system to store and retrieve information about users, their products, and conversations.

## Memory Systems Overview

### 1. Core Memory (Flat Text Storage)

**Location:** `CoreMemory` model in `ee/models/assistant.py`

**Purpose:** Team-wide, human-readable memory storage that provides context to the AI agent in every conversation.

**Characteristics:**
- One per team (OneToOne relationship)
- Stored as flat text with facts separated by newlines
- Limited to 5000 characters (truncated with middle section omitted)
- Always included in agent context via prompts
- Updated through:
  - Initial onboarding (`/init` command)
  - Continuous collection during conversations
  - Manual operations via `core_memory_append` and `core_memory_replace` tools

**When to use:**
- Foundational facts about the team's product or business
- Information that should be available to all conversations
- High-level context that doesn't need semantic search

### 2. Queryable Memory (Semantic Search System)

**Location:** `AgentMemory` model in `products/posthog_ai/backend/models.py`

**Purpose:** User-scoped, semantically searchable memory storage for detailed facts and preferences.

**Characteristics:**
- Multiple per team (ForeignKey relationship)
- User-scoped (can be per-user or team-wide)
- Stored with semantic embeddings (`text-embedding-3-small-1536`)
- Searchable via cosine distance similarity
- Backed by ClickHouse `document_embeddings` table
- Accessed through `ManageMemoriesTool` during conversations

**When to use:**
- User-specific preferences or information
- Detailed technical facts that need semantic retrieval
- Large volume of memories that exceed core memory limits
- Information that benefits from similarity search

## Automatic Synchronization

### Overview

The core memory system automatically syncs new memories to the queryable system to ensure consistency and enable semantic search across all memories.

**Implementation:** `ee/hogai/chat_agent/memory/queryable_memory_sync.py`

### How It Works

When core memory is updated, the system:

1. **Checks for similarity** - Queries existing memories using semantic search
2. **Prevents duplicates** - Skips creation if similar memory exists (cosine distance < 0.15)
3. **Creates new memory** - Adds to `AgentMemory` with automatic embedding
4. **Tags source** - Metadata includes `{"source": "core_memory"}` for tracking

### Sync Triggers

Memories are automatically synced in these scenarios:

#### 1. Memory Collection (Continuous)
**Node:** `MemoryCollectorToolsNode`

When the agent uses memory tools during conversation:
- `core_memory_append` → Syncs appended fragment
- `core_memory_replace` → Syncs new fragment (not original)

#### 2. Onboarding Completion
**Node:** `MemoryOnboardingFinalizeNode`

When `/init` onboarding completes:
- Compressed memory from Q&A pairs → Synced as single entry

### Similarity Detection

**Threshold:** 0.15 cosine distance (configurable)

**Query Logic:**
```sql
SELECT document_id, cosineDistance(embedding, embedText(query_text, model_name)) as distance
FROM document_embeddings
WHERE model_name = 'text-embedding-3-small-1536'
  AND product = 'posthog-ai'
  AND document_type = 'memory'
  AND distance < 0.15
LIMIT 1
```

**Behavior:**
- If similar memory found (distance < 0.15) → Skip creation
- If no similar memory → Create new `AgentMemory` with embedding

### Configuration

**Similarity Threshold:**
```python
SIMILARITY_THRESHOLD = 0.15  # Lower = more similar required
```

Can be overridden per call:
```python
await sync_memory_to_queryable(
    team, user, content,
    similarity_threshold=0.3  # More lenient
)
```

## Memory Workflows

### Initial Onboarding (`/init`)

1. **Context Gathering**
   - Retrieves domain/bundle ID from event taxonomy
   - Checks for product description in team settings

2. **Scraping (Optional)**
   - Fetches product info from domains
   - User confirms or rejects scraped content

3. **Q&A Collection**
   - Asks up to 3 questions about business/product
   - Stores raw Q&A pairs in `CoreMemory.initial_text`

4. **Compression**
   - LLM compresses Q&A into coherent memory
   - Saves to `CoreMemory.text`
   - **Syncs compressed memory to queryable system**

### Continuous Collection

During any conversation:

1. **Monitoring**
   - `MemoryCollectorNode` analyzes conversation
   - Identifies product-relevant information

2. **Tool Invocation**
   - Agent decides to append/replace memory
   - Calls `core_memory_append` or `core_memory_replace`

3. **Execution**
   - `MemoryCollectorToolsNode` updates core memory
   - **Syncs new/updated fragment to queryable system**

## API Usage

### Syncing Memory Manually

```python
from ee.hogai.chat_agent.memory.queryable_memory_sync import sync_memory_to_queryable

# Sync a memory fragment
memory = await sync_memory_to_queryable(
    team=team,
    user=user,  # Optional, None for team-wide
    memory_content="Important fact about the product"
)

# Returns AgentMemory if created, None if duplicate
if memory:
    print(f"Created memory {memory.id}")
else:
    print("Similar memory already exists")
```

### Checking for Similar Memories

```python
from ee.hogai.chat_agent.memory.queryable_memory_sync import _has_similar_memory

has_similar = await _has_similar_memory(
    team=team,
    content="Product uses PostgreSQL",
    threshold=0.15
)
```

### Creating Queryable Memory Directly

```python
from ee.hogai.chat_agent.memory.queryable_memory_sync import _create_queryable_memory

memory = await _create_queryable_memory(
    team=team,
    user=user,
    content="Detailed technical specification"
)
# Automatically triggers embedding
```

## Testing

### Unit Tests
Location: `ee/hogai/chat_agent/memory/test/test_queryable_memory_sync.py`

Run with:
```bash
uv run pytest ee/hogai/chat_agent/memory/test/test_queryable_memory_sync.py -v
```

### Integration Tests
Location: `ee/hogai/chat_agent/memory/test/test_nodes.py`

Specific tests for sync integration:
- `TestMemoryCollectorToolsNode::test_syncs_appended_memory_to_queryable_system`
- `TestMemoryCollectorToolsNode::test_syncs_replaced_memory_to_queryable_system`
- `TestMemoryCollectorToolsNode::test_does_not_sync_when_replace_fails`
- `TestMemoryOnboardingFinalizeNode::test_run`

Run with:
```bash
uv run pytest ee/hogai/chat_agent/memory/test/test_nodes.py::TestMemoryCollectorToolsNode -v
```

## Architecture Decisions

### Why Automatic Sync?

**Problem:** Two disconnected memory systems led to:
- Inconsistent state between core and queryable memories
- Missing context in semantic search
- Manual effort required to maintain both systems

**Solution:** Automatic one-way sync from core → queryable ensures:
- Core memories are always searchable
- No manual synchronization needed
- Single source of truth (core memory)
- Semantic search available for all memories

### Why One-Way Sync?

**Core → Queryable only** because:
- Core memory is the authoritative source (always in context)
- Queryable memory is discovery/retrieval layer
- Prevents sync conflicts and circular dependencies
- Simpler to reason about and maintain

### Why Similarity Detection?

**Problem:** Repeated conversations could create many duplicate memories.

**Solution:** Semantic similarity check prevents:
- Bloated queryable memory storage
- Redundant embeddings
- Confusing duplicate results in searches

**Trade-off:** May occasionally skip legitimate variations. Threshold tuned to balance precision vs recall.

### Why Metadata Tagging?

All synced memories include `{"source": "core_memory"}` to:
- Track provenance of memories
- Enable filtering by source
- Support future bidirectional sync if needed
- Aid debugging and monitoring

## Future Enhancements

### Potential Improvements

1. **Configurable Thresholds**
   - Per-team similarity threshold settings
   - Different thresholds for different memory types

2. **Batch Sync Management Command**
   - Sync existing core memories retroactively
   - Useful for migrations or data recovery

3. **Bidirectional Sync**
   - Sync highly-voted queryable memories back to core
   - Require approval workflow to maintain quality

4. **Metadata Enrichment**
   - Add timestamps for temporal context
   - Include conversation ID for traceability
   - Tag by topic or category

5. **Monitoring & Metrics**
   - Track duplicate prevention rate
   - Monitor sync failures
   - Dashboard for memory health

6. **Smart Consolidation**
   - Periodic deduplication of queryable memories
   - Merge similar memories with vote/confidence scores

## Troubleshooting

### Memory Not Syncing

**Check:**
1. Core memory was actually updated (check `CoreMemory.text`)
2. Feature flag `has_memory_tool_feature_flag()` is enabled
3. Content is not empty or whitespace-only
4. Embedding worker is running and processing requests

### Duplicate Memories Created

**Possible causes:**
1. Threshold too high (> 0.15)
2. Embeddings not yet generated when similarity checked
3. Different phrasing causes semantic distance > threshold

**Solutions:**
- Lower threshold to 0.1 for stricter matching
- Wait for embedding worker to process before checking
- Review and merge duplicates manually

### Sync Failures

**Common issues:**
1. Database connection issues
2. Embedding service unavailable
3. Token limit exceeded (> 8192 tokens)

**Debug steps:**
```python
# Check logs for embedding worker errors
# Verify content length
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")
token_count = len(enc.encode(content))
print(f"Tokens: {token_count}/8192")
```

## Related Documentation

- Core Memory API: `ee/api/core_memory.py`
- Manage Memories Tool: `ee/hogai/tools/manage_memories.py`
- Memory Collection Prompts: `ee/hogai/chat_agent/memory/prompts.py`
- Agent Memory Model: `products/posthog_ai/backend/models.py`
