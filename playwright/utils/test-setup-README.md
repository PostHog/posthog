# Playwright Test Database Setup Library

This library provides a powerful way to configure your database before running Playwright tests, ensuring consistent and isolated test environments.

## Overview

The system consists of two parts:
1. **Django Backend**: A `setup_test/{test_name}` endpoint that calls predefined setup functions
2. **Playwright Library**: TypeScript utilities to call the setup endpoint and manage test data

## Security

⚠️ **Important**: The setup endpoint is only accessible when `settings.TEST = True` for security reasons.

## Quick Start

### Basic Usage

```typescript
import { test, expect } from '../utils/enhanced-test-base'

test('my test with setup', async ({ page, testSetup }) => {
    // Setup a basic organization with test@posthog.com user
    const result = await testSetup.setupBasicOrganization('My Org', 'My Project')
    
    // Login and navigate to project page
    await testSetup.loginAndNavigateToProject(page, result.result.team_id)
    
    // Now you're logged in and on the project page
    // Your test assertions here...
})
```

### Available Test Fixtures

#### 1. Regular Test with Setup
```typescript
import { test } from '../utils/enhanced-test-base'

test('my test', async ({ page, testSetup }) => {
    await testSetup.setupBasicOrganization()
    // Test code...
})
```

#### 2. Test with Pre-configured Organization
```typescript
import { testWithBasicOrg } from '../utils/enhanced-test-base'

testWithBasicOrg('test with org', async ({ page, basicOrgSetup, testSetup }) => {
    // Organization already exists (creates ONE org, not multiple!)
    console.log('Organization ID:', basicOrgSetup.organizationId)
    console.log('Team ID:', basicOrgSetup.teamId)
    
    // Login and navigate to project
    await testSetup.loginAndNavigateToProject(page, basicOrgSetup.teamId)
    
    // Test code...
})
```

## Available Setup Functions

### Built-in Setup Functions

1. **`basic_organization`** - Creates organization, project, team, and test@posthog.com user
   ```typescript
   const result = await testSetup.setupBasicOrganization('Org Name', 'Project Name')
   // Then login and navigate to project:
   await testSetup.loginAndNavigateToProject(page, result.result.team_id)
   ```





2. **`insights_test`** - Sets up analytics/insights environment
   ```typescript
   await testSetup.setupInsightsTest({ create_sample_events: true })
   ```

### Custom Setup Functions

To add new setup functions:

1. **Add to Django**: Edit `posthog/test/test_setup_functions.py`
   ```python
   def setup_my_custom_test(data: Dict[str, Any]) -> Dict[str, Any]:
       # Your setup logic here
       return {"custom_data": "created"}
   
   # Add to registry
   TEST_SETUP_FUNCTIONS["my_custom_test"] = setup_my_custom_test
   ```

2. **Use in Playwright**:
   ```typescript
   const result = await testSetup.setupTest('my_custom_test', {
       data: { custom_param: 'value' }
   })
   ```

## API Reference

### TestSetup Class

#### Methods

- **`setupTest(testName, options)`** - Run any setup function
- **`setupBasicOrganization(orgName?, projectName?)`** - Create basic org structure



- **`setupInsightsTest(data?)`** - Setup insights environment
- **`loginAndNavigateToProject(page, teamId)`** - Login as test@posthog.com and go to project
- **`getAvailableTests()`** - List available setup functions

#### Options
```typescript
interface TestSetupOptions {
    data?: Record<string, any>      // Custom data for setup function
    throwOnError?: boolean          // Whether to throw on errors (default: true)
    baseURL?: string               // Custom API base URL
}
```

### Convenience Functions

```typescript
// One-off setup call
import { setupTestData } from '../utils/test-setup'

const result = await setupTestData(request, 'basic_organization', {
    organization_name: 'My Org'
})
```

## Error Handling

```typescript
// Handle errors gracefully
const result = await testSetup.setupTest('my_test', { throwOnError: false })

if (!result.success) {
    console.log('Setup failed:', result.error)
    console.log('Available tests:', result.available_tests)
}
```

## Best Practices

### 1. Test Isolation
Use separate test databases or unique identifiers to ensure test isolation:
```typescript
test('my test', async ({ page, testSetup }) => {
    // Create unique test data with timestamps or UUIDs
    await testSetup.setupBasicOrganization(`Test Org ${Date.now()}`)
})
```

### 2. Minimal Setup
Only create the data you need for each test:
```typescript
// Good: Minimal setup
await testSetup.setupBasicOrganization()

// Avoid: Over-setup
await testSetup.setupUserWithOrganization()
await testSetup.setupFeatureFlagsTest()
await testSetup.setupInsightsTest()
```

### 3. Descriptive Test Names
Use test names that match their setup requirements:
```typescript
test('dashboard with sample events', async ({ testSetup }) => {
    await testSetup.setupInsightsTest({ create_sample_events: true })
    // Test dashboard with events
})
```

### 4. Custom Setup Functions
For complex recurring setups, create dedicated setup functions:
```python
# In posthog/test/test_setup_functions.py
def setup_dashboard_with_insights(data):
    # Create org, user, sample events, insights, dashboard
    return {"dashboard_id": "123", "insight_ids": ["1", "2"]}
```

## Environment Variables

- `BASE_URL` - API base URL (default: http://localhost:8080)
- `CLEANUP_AFTER_TEST` - Set to 'false' to skip cleanup for debugging

## Troubleshooting

### Setup Endpoint Not Found
- Ensure Django server is running in TEST mode
- Check that `settings.TEST = True`
- Verify the endpoint is accessible at `/api/setup_test/{test_name}/`

### Setup Function Not Found
```typescript
// List available functions
const available = await testSetup.getAvailableTests()
console.log('Available setup functions:', available)
```

### Database Connection Issues
- Ensure test database is properly configured
- Check that database is accessible from both Django and Playwright

## Examples

See `playwright/e2e/test-setup-example.spec.ts` for comprehensive examples of all features.