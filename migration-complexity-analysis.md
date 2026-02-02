# Migration Complexity Analysis: Phase 1 → Full Trigger Groups

## The Challenge

### Phase 1 Mental Model
Users learn: "Each trigger has its own sample rate"
```
Trigger 1: /checkout → 100%
Trigger 2: /browse → 5%
Combined with: ANY or ALL
```

### Full Groups Mental Model
Users need to learn: "Triggers are grouped together with shared sample rates"
```
Group 1: [/checkout URL + flag-x] → 20%
Group 2: [/shopping URL] → 50%
Group 3: [purchase event + flag-y] → 100%
```

**Conceptual shift**: Triggers → Triggers inside Groups

## Technical Migration Complexity: MEDIUM

### Data Model Evolution

#### Phase 1 Schema
```python
# In Team model
session_recording_url_trigger_config = JSONField([
    {"url": "/checkout", "matching": "regex", "sampleRate": 1.0},
    {"url": "/browse", "matching": "regex", "sampleRate": 0.05}
])
session_recording_event_trigger_config = JSONField(["purchase"])
session_recording_linked_flag = JSONField({"flag": "flag-x"})
session_recording_sample_rate = DecimalField(0.10)
session_recording_trigger_match_type_config = CharField("any")
```

#### Full Groups Schema (after migration)
```python
# New field
session_recording_trigger_groups = JSONField([
    {
        "id": "group-1",
        "name": "Checkout Pages",
        "sampleRate": 1.0,
        "matchType": "all",
        "triggers": [
            {"type": "url", "url": "/checkout", "matching": "regex"}
        ]
    },
    {
        "id": "group-2",
        "name": "Browse Pages",
        "sampleRate": 0.05,
        "matchType": "all",
        "triggers": [
            {"type": "url", "url": "/browse", "matching": "regex"}
        ]
    }
])

# Old fields kept for backward compat or deprecated
```

### Migration Path Complexity

#### Option 1: Keep Both Systems (HIGH COMPLEXITY)
```python
# Team model has BOTH old and new fields
# SDK supports BOTH evaluation paths
# UI shows BOTH interfaces (or migrates users forcefully)

# Complexity score: 8/10
# - Dual code paths in SDK
# - Dual UI components
# - Confusing for users during transition
# - Tech debt persists indefinitely
```

#### Option 2: Auto-migrate with Deprecation (MEDIUM COMPLEXITY)
```python
# 1. Add trigger_groups field
# 2. Run migration to convert Phase 1 → Groups
# 3. Keep old fields read-only for 3-6 months
# 4. Eventually remove old fields

# Complexity score: 5/10
# - Clear migration path
# - Time-boxed tech debt
# - Users moved automatically
# - Some validation needed
```

#### Option 3: Manual Migration with Banner (MEDIUM COMPLEXITY)
```python
# 1. Add trigger_groups field
# 2. Show banner: "Upgrade to Trigger Groups"
# 3. Let users migrate at their own pace
# 4. Support both indefinitely OR force migrate after deadline

# Complexity score: 6/10
# - Gradual rollout
# - User control
# - But indefinite dual support OR angry users at deadline
```

## User Experience Complexity: HIGH

### Learning Curve Impact

**Phase 1 User Journey:**
1. User sets up URL trigger: `/checkout`
2. User adds sample rate: `100%` ← **learns this pattern**
3. User adds another trigger: `/browse` with `5%`
4. Mental model: "Triggers have rates" ✅

**Then later (Full Groups):**
1. System says: "We're upgrading to Trigger Groups!"
2. User sees new UI with groups containing triggers
3. Confusion: "Wait, I thought triggers had rates... now groups have rates?"
4. Mental model: **Must be rebuilt** ❌

This is a **breaking mental model** - the units of organization change.

### UI Confusion During Migration

```
Before (Phase 1):
┌─ Triggers ──────────────────┐
│ • /checkout → 100%          │
│ • /browse → 5%              │
└─────────────────────────────┘

After (Full Groups):
┌─ Trigger Groups ────────────┐
│  Group 1 (100%)             │
│    • /checkout              │
│  Group 2 (5%)               │
│    • /browse                │
└─────────────────────────────┘
```

Users ask: "Why the extra layer? What happened to my simple triggers?"

## Alternative: Start with "Simplified Groups" (Phase 1b)

### Concept

Start with groups from Day 1, but restrict to **one trigger per group** in Phase 1.

**User sees:**
```
┌─ Recording Rules ───────────┐
│  Rule 1: Checkout Pages     │
│    Sample: 100%             │
│    • URL matches /checkout  │
│                             │
│  Rule 2: Browse Pages       │
│    Sample: 5%               │
│    • URL matches /browse    │
│                             │
│  [+ Add Rule]               │
└─────────────────────────────┘
```

**Under the hood:** Full groups data structure, but UI constrains to 1 trigger per group.

### Data Model (Same as Full Groups!)
```python
session_recording_trigger_groups = [
    {
        "id": "rule-1",
        "name": "Checkout Pages",
        "sampleRate": 1.0,
        "matchType": "all",  # Irrelevant with 1 trigger
        "triggers": [
            {"type": "url", "url": "/checkout", "matching": "regex"}
        ]
    }
]
```

### Evolution Path

**Phase 1b → Phase 2: Just remove UI constraint**

```typescript
// Phase 1b UI constraint
function TriggerGroupEditor() {
    const maxTriggersPerGroup = 1  // Enforced in UI

    if (group.triggers.length >= maxTriggersPerGroup) {
        return <button disabled>Add Trigger (max 1 per rule)</button>
    }
}

// Phase 2: Remove constraint
function TriggerGroupEditor() {
    // const maxTriggersPerGroup = 1  // <-- Just delete this!

    return <button>Add Trigger</button>
}
```

**No data migration needed!** Just UI changes.

### Terminology Bridge

Call them "Recording Rules" or "Sampling Rules" instead of "Trigger Groups" in Phase 1b:
- Feels simpler/more concrete
- Natural evolution: "Rules can now have multiple conditions!"

## Complexity Comparison

| Approach | Data Migration | Code Complexity | User Confusion | Time to Phase 2 |
|----------|---------------|-----------------|----------------|-----------------|
| **Phase 1 (per-trigger) → Groups** | Required | High (dual systems) | High | +3 weeks |
| **Start with Simplified Groups** | None | Low (one system) | Low | +1 week |

## Recommendation: START WITH SIMPLIFIED GROUPS

### Why This Is Better

1. **No future migration**: Data model is already correct
2. **No dual code paths**: One evaluation system from start
3. **Progressive disclosure**: Simple UI now, more features later
4. **Coherent mental model**: "Rules control recording" from Day 1
5. **Faster to Phase 2**: Just UI changes, not data + SDK + migration

### Phase 1b: Simplified Groups ("Recording Rules")

**Constraints:**
- Max 1 trigger per group/rule
- matchType always "all" (hidden from UI since it's irrelevant)
- No group ordering/priority yet

**UI:**
```
┌─ Recording Rules ─────────────────────────────┐
│                                                │
│  [+ New Rule]                                  │
│                                                │
│  Rule: "High-value checkouts"                  │
│  ✓ Enabled    Sample rate: 100%              │
│  └─ When URL matches: /checkout (regex)       │
│     [Change trigger type ▼] [Remove]           │
│                                                │
│  Rule: "General browsing"                      │
│  ✓ Enabled    Sample rate: 5%                │
│  └─ When URL matches: .* (regex)              │
│     [Change trigger type ▼] [Remove]           │
│                                                │
└────────────────────────────────────────────────┘
```

Users think: "Each rule is a condition + sample rate" ✅

### Phase 2: Full Groups

**What changes:**
```diff
  Rule: "Checkout with flag enabled"
  ✓ Enabled    Sample rate: 100%
+ When: ALL of these conditions match
  └─ URL matches: /checkout (regex)
+    [+ Add condition]
+ └─ Feature flag: checkout-v2 enabled
```

Users think: "Oh, rules can have multiple conditions now!" ✅

**No reconceptualization needed** - just "more powerful rules".

## Implementation Effort Comparison

### Path A: Phase 1 (per-trigger) → Later Migrate to Groups
```
Week 1-2: Implement per-trigger sampling
  └─ Backend: add sampleRate to triggers
  └─ Frontend: add rate input per trigger
  └─ SDK: evaluate per-trigger rates

...6 months later, users request groups...

Week N: Design migration
Week N+1: Implement groups system
Week N+2: Build migration logic
Week N+3: Dual system testing
Week N+4: User migration coordination
Week N+5: Deprecate old system

Total: 2 weeks + 5 weeks later = 7 weeks
```

### Path B: Start with Simplified Groups
```
Week 1-2: Implement simplified groups
  └─ Backend: full groups model (constrained to 1 trigger)
  └─ Frontend: "rules" UI with 1 condition
  └─ SDK: groups evaluation (simple case)

...6 months later, users request multiple conditions...

Week N: Remove UI constraint
Week N+1: Add multi-condition UI
Week N+2: Test edge cases

Total: 2 weeks + 2 weeks later = 4 weeks
```

**Savings: 3 weeks of migration work**

## Technical Debt Analysis

### Path A (Phase 1 → Groups)
```python
# Backend has dual fields
class Team(Model):
    # Old Phase 1 fields
    session_recording_url_trigger_config = JSONField()  # Has sampleRate per trigger
    session_recording_event_trigger_config = JSONField()
    session_recording_sample_rate = DecimalField()

    # New Phase 2 fields
    session_recording_trigger_groups = JSONField()

    # Which one is source of truth? Both? Need sync?
```

```typescript
// SDK has dual evaluation
function shouldRecord(config) {
    if (config.triggerGroups) {
        return evaluateGroups(config.triggerGroups)  // New path
    } else {
        return evaluateLegacy(config)  // Old path
    }
}
```

**Tech debt score: 7/10** - Dual systems, unclear ownership, testing burden

### Path B (Simplified Groups from Start)
```python
# Backend has one field
class Team(Model):
    session_recording_trigger_groups = JSONField()  # Clean, single source
```

```typescript
// SDK has one evaluation path
function shouldRecord(config) {
    return evaluateGroups(config.triggerGroups)  // Always this
}
```

**Tech debt score: 2/10** - Single system, clear ownership, easier testing

## Final Recommendation

**Start with Simplified Groups** (Path B) because:

1. ✅ Same implementation time as Phase 1 (~2 weeks)
2. ✅ No future migration needed (saves 3+ weeks later)
3. ✅ No dual code paths (lower maintenance burden)
4. ✅ Coherent user mental model (no reconceptualization)
5. ✅ Easily extensible (just remove UI constraints)
6. ✅ Lower technical debt
7. ✅ Cleaner codebase

**Trade-off:**
- Slightly more upfront thinking about groups structure
- But avoids all the migration pain later

## Answer to Your Question

> "Would it be easy to go from [per-trigger] to groups later?"

**Honest answer: No, it adds significant complexity:**
- 3+ weeks of migration work
- Dual code paths in SDK, backend, and frontend
- User confusion and training
- Technical debt that's hard to remove
- Testing burden multiplies

**Better approach: Start with simplified groups**
- Same effort now, much easier later
- Clean architecture from day 1
- Progressive disclosure for users
- No breaking changes ever needed
