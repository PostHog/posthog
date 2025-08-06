/**
 * Example test demonstrating the test setup functionality
 * This file shows different ways to use the database setup library
 */

import { expect } from '@playwright/test'
import { test, testWithCleanDatabase, testWithBasicOrg } from '../utils/enhanced-test-base'
import { setupTestData } from '../utils/test-setup'

// Example 1: Manual test setup in test
test('manual setup - basic organization', async ({ page, testSetup }) => {
    // Setup test data
    const setupResult = await testSetup.setupBasicOrganization('My Test Org', 'My Test Project')
    expect(setupResult.success).toBe(true)
    expect(setupResult.result.organization_name).toBe('My Test Org')

    // Navigate to the organization
    await page.goto('/')

    // Test that the organization was created
    // (Add your actual test assertions here)
})

// Example 2: Using the convenience function
test('convenience function setup', async ({ page, request }) => {
    const setupResult = await setupTestData(request, 'user_with_organization', {
        email: 'testuser@example.com',
        organization_name: 'Test Org via Function',
    })

    expect(setupResult.success).toBe(true)
    expect(setupResult.result.user_email).toBe('testuser@example.com')

    await page.goto('/')
    // Add your test logic here
})

// Example 3: Using test with automatic clean database
testWithCleanDatabase('test with clean database', async ({ page, testSetup }) => {
    // Database is automatically cleared before this test

    await testSetup.setupFeatureFlagsTest({
        flag_name: 'test-flag',
        enabled: true,
    })

    await page.goto('/')
    // Test feature flags functionality
})

// Example 4: Using test with pre-configured organization
testWithBasicOrg('test with basic org fixture', async ({ page, organizationId, projectId, teamId }) => {
    // Organization, project, and team are already created

    await page.goto('/')
    // Test with the pre-created organization
})

// Example 5: Multiple setup calls in one test
test('multiple setup operations', async ({ page, testSetup }) => {
    // Clear database first
    await testSetup.clearDatabase()

    // Setup user and organization
    const userResult = await testSetup.setupUserWithOrganization({
        email: 'admin@test.com',
        organizationName: 'Admin Org',
    })

    // Setup insights test environment
    const insightsResult = await testSetup.setupInsightsTest({
        create_sample_events: true,
        event_count: 100,
    })

    expect(userResult.success).toBe(true)
    expect(insightsResult.success).toBe(true)

    await page.goto('/')
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
    expect(availableTests).toContain('user_with_organization')
    expect(availableTests).toContain('empty_database')
    expect(availableTests).toContain('feature_flags_test')
    expect(availableTests).toContain('insights_test')
})
