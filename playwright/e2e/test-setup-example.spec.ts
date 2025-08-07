/**
 * Example test demonstrating the test setup functionality
 * This file shows different ways to use the database setup library
 */

import { expect } from '@playwright/test'
import { test, testWithBasicOrg } from '../utils/enhanced-test-base'
import { setupTestData } from '../utils/test-setup'

// Example 1: Setup organization and login to project page
test('setup organization and login', async ({ page, testSetup }) => {
    // Setup test data - creates org, project, team and test@posthog.com user
    const setupResult = await testSetup.setupBasicOrganization('My Test Org', 'My Test Project')
    expect(setupResult.success).toBe(true)
    expect(setupResult.result.organization_name).toBe('My Test Org')
    expect(setupResult.result.user_email).toBe('test@posthog.com')

    // Login as test@posthog.com and navigate to the project page
    await testSetup.loginAndNavigateToProject(page, setupResult.result.team_id)

    // Now you're logged in and on the project page
    // Add your test logic here
})

// Example 2: Using the convenience function
test('convenience function setup', async ({ page, request }) => {
    const setupResult = await setupTestData(request, 'basic_organization', {
        organization_name: 'Test Org via Function',
        project_name: 'Test Project',
    })

    expect(setupResult.success).toBe(true)
    expect(setupResult.result.user_email).toBe('test@posthog.com')

    await page.goto('/')
    // Add your test logic here
})

// Example 3: Insights test setup
test('insights setup test', async ({ page, testSetup }) => {
    await testSetup.setupInsightsTest({
        create_sample_events: true,
        event_count: 50,
    })

    await page.goto('/')
    // Test insights functionality
})

// Example 4: Using test with pre-configured organization
testWithBasicOrg('test with basic org fixture', async ({ page, basicOrgSetup, testSetup }) => {
    // Organization, project, and team are already created (ONE organization, not three!)

    // Login and navigate to the project page
    await testSetup.loginAndNavigateToProject(page, basicOrgSetup.teamId)

    // Test with the pre-created organization
})

// Example 5: Multiple setup calls in one test
test('multiple setup operations', async ({ page, testSetup }) => {
    // Setup basic organization
    const orgResult = await testSetup.setupBasicOrganization('Admin Org', 'Admin Project')

    // Setup insights test environment
    const insightsResult = await testSetup.setupInsightsTest({
        create_sample_events: true,
        event_count: 100,
    })

    expect(orgResult.success).toBe(true)
    expect(insightsResult.success).toBe(true)

    // Login and navigate to project
    await testSetup.loginAndNavigateToProject(page, orgResult.result.team_id)

    // Test insights functionality with sample data
})

// Example 6: Error handling
test('test setup error handling', async ({ testSetup }) => {
    // Test with invalid setup function name
    const result = await testSetup.setupTest('invalid_function_name', { throwOnError: false })

    expect(result.success).toBe(false)
    expect(result.error).toContain('not found')
    expect(result.available_tests).toBeDefined()
    expect(result.available_tests).toContain('basic_organization')
})

// Example 7: Custom test setup function (requires adding to the registry)
test('custom setup - insights with events', async ({ page, testSetup }) => {
    const setupResult = await testSetup.setupTest('insights_test', {
        data: {
            organization_name: 'Analytics Org',
            create_sample_events: true,
            event_types: ['pageview', 'click', 'purchase'],
            user_count: 50,
            event_count_per_user: 20,
        },
    })

    expect(setupResult.success).toBe(true)

    await page.goto('/insights')
    // Test insights page with pre-populated data
})

// Example 8: Testing the setup API directly
test('test setup API availability', async ({ testSetup }) => {
    const availableTests = await testSetup.getAvailableTests()

    expect(availableTests).toContain('basic_organization')
    expect(availableTests).toContain('insights_test')
})
