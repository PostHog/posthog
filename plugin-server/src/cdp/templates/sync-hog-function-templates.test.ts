import { parseJSON } from '~/src/utils/json-parse'

import { defaultConfig } from '../../config/config'
import { Hub } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { HOG_FUNCTION_TEMPLATES } from './index'
import { TemplateSyncService } from './sync-hog-function-templates'

describe('TemplateSyncService', () => {
    let hub: Hub
    let service: TemplateSyncService
    let postgres: PostgresRouter
    let geoipTemplate: any

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)

        // Create a minimal hub with a real database connection
        hub = {
            postgres,
            instanceId: new UUIDT().toString(),
        } as unknown as Hub

        service = new TemplateSyncService(hub)

        // Find the geoip template to use in our tests
        geoipTemplate = HOG_FUNCTION_TEMPLATES.find((template) => template.id === 'template-geoip')

        // If geoip template doesn't exist, find another template
        if (!geoipTemplate) {
            geoipTemplate = HOG_FUNCTION_TEMPLATES[0]
        }

        // Clean up any existing test templates before each test
        await cleanupTestTemplate(postgres)
    })

    afterAll(async () => {
        await cleanupTestTemplate(postgres)
        await postgres.end()
    })

    /**
     * Helper to clean up test templates from the database
     */
    async function cleanupTestTemplate(postgres: PostgresRouter) {
        try {
            // Delete all entries from posthog_hogfunction
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_hogfunction`,
                [],
                'cleanup-all-hogfunctions'
            )

            // Delete all templates
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_hogfunctiontemplate`,
                [],
                'cleanup-all-templates'
            )
        } catch (error) {
            // If table doesn't exist yet, that's fine
            console.log('Template cleanup error (can be ignored if table does not exist)', error)
        }
    }

    it('should create a new template when it does not exist', async () => {
        // Process the template
        const result = await service.processTemplate(geoipTemplate)

        // Check result type
        expect(result).toBe('created')

        // Verify template exists in the database
        const dbResult = await postgres.query(
            PostgresUse.COMMON_READ,
            'SELECT * FROM posthog_hogfunctiontemplate WHERE template_id = $1',
            [geoipTemplate.id],
            'verify-template-exists'
        )

        // Verify basic template properties
        expect(dbResult.rows.length).toBe(1)
        const savedTemplate = dbResult.rows[0]

        expect(savedTemplate.name).toBe(geoipTemplate.name)
        expect(savedTemplate.description).toBe(geoipTemplate.description)
        expect(savedTemplate.template_id).toBe(geoipTemplate.id)
        expect(savedTemplate.code).toBe(geoipTemplate.hog)
        expect(savedTemplate.status).toBe(geoipTemplate.status)
        expect(savedTemplate.type).toBe(geoipTemplate.type)
        expect(savedTemplate.free).toBe(geoipTemplate.free)

        // Verify input schema is properly saved
        // Note: database may store it differently than the original array
        expect(savedTemplate.inputs_schema).toBeDefined()

        // Verify the bytecode was generated
        expect(savedTemplate.bytecode).not.toBeNull()
    })

    it('should skip template when it already exists with the same SHA', async () => {
        // Insert it first
        await service.processTemplate(geoipTemplate)

        // Try to process it again - should be skipped since it hasn't changed
        const result = await service.processTemplate(geoipTemplate)

        // Check result is skipped
        expect(result).toBe('skipped')
    })

    it('should update template when it exists with a different SHA', async () => {
        // Insert the template
        await service.processTemplate(geoipTemplate)

        // Modify the template - create a deep clone to avoid modifying the original
        const modifiedTemplate = parseJSON(JSON.stringify(geoipTemplate))

        // Modify the code property which is used in SHA calculation
        modifiedTemplate.hog = geoipTemplate.hog + '\n// Modified template code'
        modifiedTemplate.name = 'Updated GeoIP Template'
        modifiedTemplate.description = 'Updated Description'

        // Process the modified template
        const result = await service.processTemplate(modifiedTemplate)

        // Check result type
        expect(result).toBe('updated')

        // Verify template was updated in the database
        const dbResult = await postgres.query(
            PostgresUse.COMMON_READ,
            'SELECT * FROM posthog_hogfunctiontemplate WHERE template_id = $1',
            [geoipTemplate.id],
            'verify-template-updated'
        )

        expect(dbResult.rows.length).toBe(1)
        const updatedTemplate = dbResult.rows[0]

        // Verify all updated properties
        expect(updatedTemplate.name).toBe('Updated GeoIP Template')
        expect(updatedTemplate.description).toBe('Updated Description')
        expect(updatedTemplate.code).toBe(modifiedTemplate.hog)

        // Check that the SHA exists but don't check its value
        expect(updatedTemplate.sha).toBeDefined()
        expect(updatedTemplate.sha.length).toBe(8)

        // Verify the bytecode was regenerated
        expect(updatedTemplate.bytecode).not.toBeNull()

        // Restore original template so subsequent tests are not affected
        await service.processTemplate(geoipTemplate)
    })

    it('SHA hashes should be consistent for identical templates and different for modified templates', async () => {
        // Insert the original template
        await service.processTemplate(geoipTemplate)
        const originalResult = await postgres.query(
            PostgresUse.COMMON_READ,
            'SELECT sha FROM posthog_hogfunctiontemplate WHERE template_id = $1',
            [geoipTemplate.id],
            'original-sha-check'
        )
        const originalSha = originalResult.rows[0].sha

        // Process it again - should be skipped with same SHA
        await service.processTemplate(geoipTemplate)
        const unchangedResult = await postgres.query(
            PostgresUse.COMMON_READ,
            'SELECT sha FROM posthog_hogfunctiontemplate WHERE template_id = $1',
            [geoipTemplate.id],
            'unchanged-sha-check'
        )
        const unchangedSha = unchangedResult.rows[0].sha

        // Verify SHA hasn't changed
        expect(unchangedSha).toBe(originalSha)

        // Now modify the template
        const modifiedTemplate = parseJSON(JSON.stringify(geoipTemplate))
        modifiedTemplate.hog = geoipTemplate.hog + '\n// Modified template'

        // Process the modified template
        await service.processTemplate(modifiedTemplate)

        // Get the new SHA
        const modifiedResult = await postgres.query(
            PostgresUse.COMMON_READ,
            'SELECT sha FROM posthog_hogfunctiontemplate WHERE template_id = $1',
            [geoipTemplate.id],
            'modified-sha-check'
        )
        const modifiedSha = modifiedResult.rows[0].sha

        // Verify the SHA has changed
        expect(modifiedSha).not.toBe(originalSha)

        // SHA length should be 8 characters (as per the implementation)
        expect(originalSha.length).toBe(8)
        expect(modifiedSha.length).toBe(8)

        // Restore the original template
        await service.processTemplate(geoipTemplate)
    })
})
