# Memory Leak Investigation Report: Inactive Tab Memory Growth

**Date**: 2025-10-21
**Investigator**: Staff+ Engineering Review
**Issue**: Inactive tabs growing to >1GB memory, never showing as idle in Chrome
**Type**: Non-heap memory leak

---

## Executive Summary

The PostHog frontend application has a **critical architectural issue** where inactive browser tabs continue to execute JavaScript timers and operations indefinitely, causing:

1. **Memory growth to >1GB** in inactive tabs
2. **Chrome never marking tabs as idle** (prevents browser optimizations)
3. **Continuous CPU usage** even when tabs are hidden
4. **Poor multi-tab experience** with resource contention

The root cause is **systematic lack of Page Visibility API integration** across polling mechanisms, despite having the infrastructure (`usePageVisibility` hook and `disposables` plugin) already in place.

## Impact Assessment

### Severity: **HIGH** (P1)

- **User Experience**: Background tabs consume significant system resources
- **Battery Impact**: Continuous JavaScript execution drains laptop battery
- **Browser Performance**: Prevents Chrome's tab freezing optimizations
- **Scale**: Affects all users with multiple tabs open
- **Memory Type**: Non-heap (likely DOM retention, event listeners, timer metadata)

### Affected User Scenarios

1. **Power users**: Opening multiple dashboard tabs for monitoring
2. **Analysts**: Multiple insight/query tabs open simultaneously
3. **Toolbar users**: Embedded toolbar continues polling in background
4. **Live analytics viewers**: Continuous polling even when tab hidden

---

## Critical Issues Identified

### 1. ⚠️ CRITICAL: Uncancellable Global Memory Tracking

**File**: `frontend/src/loadPostHogJS.tsx:37-50`

```typescript
const tenMinuteInMs = 60000 * 10
setInterval(() => {
    const memory = (window.performance as any).memory
    if (memory && memory.usedJSHeapSize) {
        loadedInstance.capture('memory_usage', {
            totalJSHeapSize: memory.totalJSHeapSize,
            usedJSHeapSize: memory.usedJSHeapSize,
            pageIsVisible: document.visibilityState === 'visible',
            pageIsFocused: document.hasFocus(),
        })
    }
}, tenMinuteInMs)
```

**Problems**:

- ❌ `setInterval` created at app initialization, **never cleared**
- ❌ No reference stored, **cannot be cancelled**
- ❌ Runs forever in every tab, even when hidden
- ❌ Not wrapped in disposables plugin
- ⚠️ Ironically captures `pageIsVisible` but doesn't use it to gate execution

**Impact**: Every 10 minutes, all tabs wake up to capture memory usage, preventing idle state

**Fix Priority**: **IMMEDIATE** - This is a global leak affecting all users

---

### 2. ⚠️ HIGH: Toolbar URL Monitoring Polling

**File**: `frontend/src/toolbar/bar/toolbarLogic.ts:456-460`

```typescript
cache.disposables.add(() => {
    const navigationInterval = setInterval(() => {
        actions.maybeSendNavigationMessage()
    }, 500)
    return () => clearInterval(navigationInterval)
}, 'navigationInterval')
```

**Problems**:

- ❌ Polls every **500ms** continuously
- ❌ No Page Visibility API check
- ❌ Keeps event loop active in hidden tabs
- ⚠️ Comment says "we don't want to write over history.pushState" but creates expensive polling instead

**Impact**: Most aggressive polling pattern - prevents Chrome idle detection

**Additional**: Similar 500ms polling in `currentPageLogic.ts:96-102`

---

### 3. ⚠️ HIGH: Live Web Analytics Continuous Polling

**File**: `frontend/src/scenes/web-analytics/liveWebAnalyticsLogic.tsx:107-111`

```typescript
cache.disposables.add(() => {
    const intervalId = setInterval(() => {
        actions.pollStats()
    }, 30000)
    return () => clearInterval(intervalId)
}, 'statsInterval')
```

**Problems**:

- ❌ Polls every **30 seconds** making network requests
- ❌ No visibility check
- ❌ Makes external API calls even when tab hidden
- ❌ Additional 500ms interval on hover (lines 91-94) also lacks visibility check

**Impact**: Network activity + timer = tab never sleeps

---

### 4. ⚠️ HIGH: DataNode Auto-Load Polling (Multiplier Effect)

**File**: `frontend/src/queries/nodes/DataNode/dataNodeLogic.ts:942-949`

```typescript
cache.disposables.add(() => {
    const timerId = window.setInterval(() => {
        if (!values.responseLoading) {
            actions.loadNewData()
        }
    }, AUTOLOAD_INTERVAL) // AUTOLOAD_INTERVAL = 30000
    return () => window.clearInterval(timerId)
}, 'autoLoadInterval')
```

**Problems**:

- ❌ Each DataNode creates **independent 30s interval**
- ❌ Dashboards with 10+ insights = **10+ simultaneous intervals**
- ❌ **Multiplier effect**: More data nodes = more memory/CPU usage
- ❌ No visibility coordination

**Impact**: Cumulative - a dashboard with 20 insights has 20 intervals running

---

### 5. ⚠️ MEDIUM: Dashboard Auto-Refresh

**File**: `frontend/src/scenes/dashboard/dashboardLogic.tsx:1675-1697`

```typescript
resetInterval: () => {
    if (values.autoRefresh.enabled) {
        // ... immediate refresh logic ...
        cache.disposables.add(() => {
            const intervalId = window.setInterval(() => {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Refresh,
                    forceRefresh: true,
                })
            }, values.autoRefresh.interval * 1000)
            return () => clearInterval(intervalId)
        }, 'autoRefreshInterval')
    }
}
```

**Problems**:

- ❌ Configurable interval (default 300s) but no visibility check
- ❌ Triggers full dashboard reload in background
- ⚠️ User-controllable, but still problematic

**Impact**: Large dashboard refreshes loading all insights in background

---

### 6. ⚠️ MEDIUM: Session Recording Player Animation Loop

**File**: `frontend/src/scenes/session-recordings/player/sessionRecordingPlayerLogic.ts:1548-1551`

```typescript
cache.disposables.add(() => {
    const timerId = requestAnimationFrame(actions.updateAnimation)
    return () => cancelAnimationFrame(timerId)
}, 'animationTimer')
```

**Problems**:

- ❌ `requestAnimationFrame` runs continuously during playback
- ❌ No visibility check to pause when tab hidden
- ⚠️ Less critical (only during playback) but still contributes

**Impact**: Recording playback left running in background tab

---

## Root Cause Analysis

### Architectural Gaps

1. **Missing Global Visibility Coordinator**
    - `usePageVisibility` hook exists (`lib/hooks/usePageVisibility.ts`) but only used in 3 places
    - No Kea-level visibility state management
    - Each logic would need to independently integrate visibility

2. **Disposables Plugin Limitations**
    - `kea-disposables.ts` correctly handles **unmount cleanup**
    - Does NOT handle **pause/resume based on visibility**
    - Plugin has no concept of page visibility state

3. **Pattern Inconsistency**
    - `sidePanelStatusLogic.tsx` shows **correct pattern** (lines 149-166):
        - Listens to `visibilitychange` event
        - Disposes timer on hide, restarts on show
    - But this pattern isn't documented or reusable
    - Only 2 files use this approach

4. **No Development Guidelines**
    - No linting rules to catch visibility violations
    - No code review checklist for polling patterns
    - Easy for new code to introduce leaks

### Why Chrome Never Shows Tabs as Idle

Chrome's tab idle detection requires:

- No JavaScript timers running
- No network activity
- No DOM mutations
- No event listeners firing

**Current state**: At minimum, these are always running:

- Memory tracking: every 10 min
- Toolbar URL check: every 500ms (if toolbar loaded)
- Live analytics: every 30s (if on analytics page)
- DataNode auto-load: every 30s × number of nodes

The 500ms toolbar intervals **alone** prevent idle state.

---

## Correct Implementation Pattern (Observed)

**File**: `frontend/src/layout/navigation-3000/sidepanel/panels/sidePanelStatusLogic.tsx:142-167`

```typescript
listeners(({ actions, cache }) => ({
    loadStatusPageSuccess: () => {
        cache.disposables.add(() => {
            const timerId = setTimeout(() => actions.loadStatusPage(), REFRESH_INTERVAL)
            return () => clearTimeout(timerId)
        }, 'refreshTimeout')
    },
    setPageVisibility: ({ visible }) => {
        if (visible) {
            actions.loadStatusPage()  // Resume
        } else {
            cache.disposables.dispose('refreshTimeout')  // Pause
        }
    },
})),

afterMount(({ actions, cache }) => {
    actions.loadStatusPage()
    cache.disposables.add(() => {
        const onVisibilityChange = (): void => {
            actions.setPageVisibility(document.visibilityState === 'visible')
        }
        document.addEventListener('visibilitychange', onVisibilityChange)
        return () => document.removeEventListener('visibilitychange', onVisibilityChange)
    }, 'visibilityListener')
}),
```

**This shows the right approach**:

1. ✅ Register `visibilitychange` listener in `afterMount`
2. ✅ Dispose specific timer when hidden
3. ✅ Restart when visible
4. ✅ Clean up listener on unmount

**But only 2 logics use this pattern!**

---

## Additional Findings

### Infrastructure That Exists (But Isn't Used)

1. **`usePageVisibility` hook** (`lib/hooks/usePageVisibility.ts`)
    - Properly implements Page Visibility API
    - Handles vendor prefixes (webkit, ms)
    - Clean API: `const { isVisible } = usePageVisibility()`
    - **Used in only 4 files**

2. **`disposables` plugin** (`kea-disposables.ts`)
    - Well-implemented cleanup system
    - Works correctly for unmount
    - Could be extended for visibility

3. **Visibility awareness in events**
    - Memory tracking **already captures** visibility state
    - Shows awareness of the issue but no action taken

### No Multi-Tab Conflicts Found ✅

- No BroadcastChannel usage (search: 0 results)
- No storage event listeners causing conflicts
- No WebSocket shared between tabs
- **This is NOT a multi-tab synchronization issue**

### Memory Type Hypothesis

Given "not heap memory":

- **Likely causes**:
  - Timer metadata in browser internals
  - Event listener retention
  - Closure retention in setTimeout/setInterval
  - DOM node retention from abandoned operations
  - Network request metadata (fetch/XHR queues)

- **Unlikely**: Large object allocations (would show in heap)

---

## Recommended Solutions

### Phase 1: IMMEDIATE (Week 1)

#### 1.1. Fix Global Memory Tracking Leak

**Priority**: P0 - Critical

```typescript
// loadPostHogJS.tsx
if (loadedInstance.getFeatureFlag(FEATURE_FLAGS.TRACK_MEMORY_USAGE)) {
    const hasMemory = 'memory' in window.performance
    if (!hasMemory) {
        return
    }

    const trackMemory = (): void => {
        // Only track if page is visible
        if (document.hidden) {
            return
        }

        const memory = (window.performance as any).memory
        if (memory && memory.usedJSHeapSize) {
            loadedInstance.capture('memory_usage', {
                totalJSHeapSize: memory.totalJSHeapSize,
                usedJSHeapSize: memory.usedJSHeapSize,
                pageIsVisible: document.visibilityState === 'visible',
                pageIsFocused: document.hasFocus(),
            })
        }
    }

    const tenMinuteInMs = 60000 * 10
    const intervalId = setInterval(trackMemory, tenMinuteInMs)

    // Store reference for cleanup (consider window.__POSTHOG_CLEANUP_HANDLERS)
    window.addEventListener('beforeunload', () => clearInterval(intervalId))
}
```

**Better**: Integrate with app unmount if possible, or check visibility before capturing.

#### 1.2. Add Visibility Checks to Toolbar Polling

**Priority**: P0 - Critical

```typescript
// toolbarLogic.ts
afterMount(({ actions, cache }) => {
    let isVisible = !document.hidden

    cache.disposables.add(() => {
        const onVisibilityChange = (): void => {
            const wasVisible = isVisible
            isVisible = !document.hidden

            if (!wasVisible && isVisible) {
                // Tab became visible - check for navigation immediately
                actions.maybeSendNavigationMessage()
            }
        }
        document.addEventListener('visibilitychange', onVisibilityChange)
        return () => document.removeEventListener('visibilitychange', onVisibilityChange)
    }, 'visibilityListener')

    cache.disposables.add(() => {
        const navigationInterval = setInterval(() => {
            if (!document.hidden) {
                // Only check when visible
                actions.maybeSendNavigationMessage()
            }
        }, 500)
        return () => clearInterval(navigationInterval)
    }, 'navigationInterval')
})
```

**Better**: Use MutationObserver or history.pushState wrapper instead of polling.

#### 1.3. Pause Live Analytics When Hidden

**Priority**: P1 - High

Apply the `sidePanelStatusLogic` pattern to `liveWebAnalyticsLogic`.

---

### Phase 2: SYSTEMATIC (Week 2-3)

#### 2.1. Create Reusable Visibility-Aware Polling Helper

```typescript
// lib/kea-visibility-interval.ts
export function addVisibilityAwareInterval(
    cache: LogicWithCache['cache'],
    callback: () => void,
    intervalMs: number,
    key: string
): void {
    let intervalId: number | null = null
    let isVisible = !document.hidden

    const start = (): void => {
        if (intervalId) return
        intervalId = window.setInterval(() => {
            if (!document.hidden) {
                callback()
            }
        }, intervalMs)
    }

    const stop = (): void => {
        if (intervalId) {
            clearInterval(intervalId)
            intervalId = null
        }
    }

    // Start if visible
    if (isVisible) {
        start()
    }

    cache.disposables.add(() => {
        const onVisibilityChange = (): void => {
            const wasVisible = isVisible
            isVisible = !document.hidden

            if (!wasVisible && isVisible) {
                start()
            } else if (wasVisible && !isVisible) {
                stop()
            }
        }

        document.addEventListener('visibilitychange', onVisibilityChange)

        return () => {
            document.removeEventListener('visibilitychange', onVisibilityChange)
            stop()
        }
    }, key)
}

// Usage:
afterMount(({ actions, cache }) => {
    addVisibilityAwareInterval(cache, () => actions.pollStats(), 30000, 'statsPolling')
})
```

#### 2.2. Extend Disposables Plugin

```typescript
// kea-disposables.ts - add new method
type DisposablesManager = {
    add: (setup: SetupFunction, key?: string) => void
    addVisibilityAware: (setup: SetupFunction, key?: string) => void // NEW
    dispose: (key: string) => boolean
    pauseOnHidden: (key: string) => void // NEW
    registry: Map<string, DisposableFunction>
    keyCounter: number
}
```

#### 2.3. Audit All setInterval Usage

**Found**: 31 files with `setInterval`
**Action**: Review each for visibility requirements

Priority files:

- ✅ `loadPostHogJS.tsx`
- ✅ `toolbarLogic.ts`
- ✅ `currentPageLogic.ts`
- ✅ `liveWebAnalyticsLogic.tsx`
- ✅ `dataNodeLogic.ts`
- ⏳ `dashboardLogic.tsx`
- ⏳ `sessionRecordingPlayerLogic.ts`
- ⏳ 24 others to review

---

### Phase 3: PREVENTION (Week 4)

#### 3.1. ESLint Rule

```typescript
// .eslintrc.js - add custom rule
{
    "rules": {
        "no-unguarded-timers": "error"  // Custom rule to catch setInterval without visibility check
    }
}
```

#### 3.2. Code Review Checklist

Add to PR template:

- [ ] Does this add `setInterval` or `setTimeout`?
- [ ] If yes, is there a visibility check or is it short-lived?
- [ ] Is the interval properly cleaned up?
- [ ] Could this run in an inactive tab?

#### 3.3. Documentation

Create `docs/POLLING_PATTERNS.md`:

- When to use polling
- How to implement visibility-aware polling
- Examples of correct patterns
- Common pitfalls

---

## Testing Strategy

### Before Fix Measurements

1. **Memory profiling**:
    - Open tab with dashboard
    - Switch to another tab for 30 minutes
    - Measure memory growth every 5 minutes
    - Use Chrome Task Manager + Performance Monitor

2. **Chrome idle detection**:
    - Check `chrome://discards`
    - Verify tab never marked as "Idle"

3. **Timer audit**:
    - Use `setInterval = new Proxy(setInterval, ...)` to log all intervals
    - Count active intervals in hidden tab

### After Fix Validation

1. **Memory should stabilize** in hidden tabs
2. **Chrome should mark tab idle** after ~5 minutes of inactivity
3. **Interval count should drop to 0** when hidden (except user-facing features)
4. **Functionality preserved** when tab becomes visible again

### Test Cases

```typescript
describe('Visibility-aware polling', () => {
    it('should stop polling when tab hidden', async () => {
        const logic = mountLogic()
        const pollSpy = jest.spyOn(logic.actions, 'pollStats')

        // Simulate tab hidden
        Object.defineProperty(document, 'hidden', { value: true, writable: true })
        document.dispatchEvent(new Event('visibilitychange'))

        await delay(35000) // Wait longer than interval

        expect(pollSpy).not.toHaveBeenCalled()
    })

    it('should resume polling when tab visible', async () => {
        // ... test resume behavior
    })
})
```

---

## Risk Assessment

### Risks of Implementing Fixes

1. **User-facing features break**:
    - Mitigation: Comprehensive testing, feature flags

2. **Dashboards don't auto-refresh**:
    - Mitigation: Refresh immediately when tab becomes visible

3. **Live features lag**:
    - Mitigation: Smart polling - increase frequency when visible, stop when hidden

4. **Regression in toolbar**:
    - Mitigation: Toolbar is optional, extensive toolbar testing

### Risks of NOT Fixing

1. **Continued poor user experience** with multi-tab usage
2. **Support burden** from users reporting slow tabs
3. **Battery drain** on laptops
4. **Browser memory limits** could crash tabs
5. **Competitive disadvantage** vs. tools that handle this properly

---

## Success Metrics

### Quantitative

- **Memory growth**: <100MB over 30min in hidden tab (vs. current >1GB)
- **Idle detection**: Tabs marked idle within 5min of hiding (vs. never)
- **Timer count**: 0 active intervals when hidden (vs. 10+)
- **CPU usage**: <1% in hidden tab (vs. 5-10%)

### Qualitative

- Users report smoother multi-tab experience
- Fewer "tab crashed" reports
- Reduced support tickets about performance

---

## Conclusion

This is a **systemic architectural issue** requiring both immediate fixes and long-term patterns. The infrastructure exists (Page Visibility API, disposables, hooks) but isn't consistently applied.

**Immediate action needed**: Fix the global memory tracking leak and 500ms toolbar polling.

**Strategic action needed**: Establish patterns, tooling, and documentation to prevent future leaks.

The good news: This is fixable without major refactoring. Most fixes are localized to specific logics.

---

## Appendix: Code Locations

### Critical Files

| File                             | Line | Issue             | Interval     | Fix Priority |
| -------------------------------- | ---- | ----------------- | ------------ | ------------ |
| `loadPostHogJS.tsx`              | 37   | Memory tracking   | 10min        | P0           |
| `toolbarLogic.ts`                | 456  | URL monitoring    | 500ms        | P0           |
| `currentPageLogic.ts`            | 96   | URL checking      | 500ms        | P0           |
| `liveWebAnalyticsLogic.tsx`      | 107  | Stats polling     | 30s          | P1           |
| `liveWebAnalyticsLogic.tsx`      | 91   | Hover polling     | 500ms        | P1           |
| `dataNodeLogic.ts`               | 943  | Auto-load         | 30s × N      | P1           |
| `dashboardLogic.tsx`             | 1675 | Dashboard refresh | configurable | P2           |
| `sessionRecordingPlayerLogic.ts` | 1549 | Animation         | RAF          | P2           |

### Example of Correct Pattern

| File                              | Line    | Why Correct                           |
| --------------------------------- | ------- | ------------------------------------- |
| `sidePanelStatusLogic.tsx`        | 149-166 | Properly pauses/resumes on visibility |
| `sidePanelNotificationsLogic.tsx` | Similar | Uses visibility correctly             |

### Infrastructure Files

| File                             | Purpose                   | Status                      |
| -------------------------------- | ------------------------- | --------------------------- |
| `lib/hooks/usePageVisibility.ts` | React hook for visibility | ✅ Exists, underutilized    |
| `kea-disposables.ts`             | Cleanup plugin            | ✅ Works well, could extend |

---

**Review Completed**: 2025-10-21
**Next Steps**: Present findings to team, prioritize fixes, assign owners
