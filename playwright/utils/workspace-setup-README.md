# PostHog Workspace Setup for Playwright

A clean, type-safe library for creating PostHog workspaces in your Playwright tests.

## What This Does

Creates complete PostHog workspaces for testing:
- **Organization** (top-level account, e.g., "Acme Corp")
- **Project** (within org, e.g., "Web App") 
- **Team/Environment** (within project, where data lives)
- **User** (`test@posthog.com` with password `12345678`)

## Quick Start

```typescript
import { test, testWithWorkspace } from '../utils/enhanced-test-base'

// Option 1: Manual workspace creation
test('my test', async ({ page, workspaceSetup }) => {
    const workspace = await workspaceSetup.createWorkspace('My Org', 'My Project')
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
    
    // Test your feature - you're now logged in on /project/{teamId}
})

// Option 2: Auto-created workspace (easier)
testWithWorkspace('my test', async ({ page, workspace, workspaceSetup }) => {
    // Workspace already exists
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
    
    // Test your feature
})
```

## Available Test Fixtures

### `test` - Basic test with workspace setup capability
```typescript
test('my test', async ({ page, workspaceSetup }) => {
    const workspace = await workspaceSetup.createWorkspace()
    // Manual setup, full control
})
```

### `testWithWorkspace` - Pre-created workspace
```typescript
testWithWorkspace('my test', async ({ page, workspace, workspaceSetup }) => {
    // workspace = { organizationId, projectId, teamId, userEmail, ... }
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
})
```

### `testWithAnalytics` - Analytics workspace with sample data
```typescript
testWithAnalytics('test dashboard', async ({ page, workspace, workspaceSetup }) => {
    // workspace.analytics_ready === true
    // Sample events/data created for testing insights
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
})
```

## Main API

### `workspaceSetup.createWorkspace(orgName?, projectName?)`
Creates: Organization → Project → Team + test@posthog.com user

```typescript
const workspace = await workspaceSetup.createWorkspace('Acme Corp', 'Web App')
// Returns: { organizationId, projectId, teamId, userEmail, ... }
```

### `workspaceSetup.createAnalyticsWorkspace(options?)`
Creates workspace + sample analytics data

```typescript
const workspace = await workspaceSetup.createAnalyticsWorkspace({
    organizationName: 'Analytics Corp',
    createSampleEvents: true,
    eventCount: 100,
    eventTypes: ['page_view', 'button_click']
})
```

### `workspaceSetup.loginAndNavigateToTeam(page, teamId)`
Logs in as test@posthog.com and goes to `/project/{teamId}`

```typescript
await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
// Now on project page, ready to test
```

## Security

⚠️ **Important**: The setup endpoint only works when `settings.TEST = True` in Django.

## Example Patterns

### Testing Different Organizations
```typescript
test('multi-org test', async ({ page, workspaceSetup }) => {
    const orgA = await workspaceSetup.createWorkspace('Company A')
    const orgB = await workspaceSetup.createWorkspace('Company B')
    
    // Test Company A
    await workspaceSetup.loginAndNavigateToTeam(page, orgA.teamId)
    // ... test logic
    
    // Switch to Company B  
    await workspaceSetup.loginAndNavigateToTeam(page, orgB.teamId)
    // ... test logic
})
```

### Testing Analytics Features
```typescript
testWithAnalytics('insights dashboard', async ({ page, workspace, workspaceSetup }) => {
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
    
    // Navigate to insights with sample data already present
    await page.goto(`/project/${workspace.teamId}/insights`)
    await expect(page.locator('[data-attr="event-count"]')).toBeVisible()
})
```

### Custom Analytics Setup
```typescript
test('custom analytics', async ({ page, workspaceSetup }) => {
    const workspace = await workspaceSetup.createAnalyticsWorkspace({
        organizationName: 'Analytics Test',
        createSampleEvents: true,
        eventCount: 1000,
        eventTypes: ['purchase', 'signup', 'page_view']
    })
    
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
    // Test with 1000 sample events of specified types
})
```

## PostHog Workspace Structure

```
Organization (Acme Corp)
├── Project (Web App)
│   ├── Team (Web App Default) ← This is where you test
│   └── Settings, Users, etc.
└── Project (Mobile App)
    └── Team (Mobile App Default)
```

The **Team** is where all your data lives (events, users, insights, etc.). That's why you navigate to `/project/{teamId}` - it's the team's project page.

## Available Workspace Types

Backend endpoint types:
- `organization_with_team` - Basic workspace
- `analytics_workspace` - Workspace + sample analytics data

## Error Handling

```typescript
test('handle errors', async ({ workspaceSetup }) => {
    // Check available types
    const types = await workspaceSetup.getAvailableSetupTypes()
    expect(types).toContain('organization_with_team')
    
    // Graceful error handling
    try {
        await workspaceSetup.createWorkspace()
    } catch (error) {
        console.log('Setup failed:', error.message)
    }
})
```

## Migration from Old API

If you have existing tests using the old API:

```typescript
// Old (messy)
const result = await testSetup.setupBasicOrganization()
await testSetup.loginAndNavigateToProject(page, result.result.team_id)

// New (clean) 
const workspace = await workspaceSetup.createWorkspace()
await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
```

The new API is cleaner, more intuitive, and follows PostHog's actual data model more closely.