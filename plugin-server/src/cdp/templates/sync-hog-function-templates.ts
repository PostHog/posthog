import crypto from 'crypto'

import { insertRow } from '../../../tests/helpers/sql'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import { compileHog } from './compiler'
import { HOG_FUNCTION_TEMPLATES_FOR_TESTS } from './index'
import { HogFunctionTemplate } from './types'

export class TemplateSyncService {
    private db: PostgresRouter

    constructor(db: PostgresRouter) {
        this.db = db
    }

    /**
     * Sync all templates to the database
     */
    public async syncTemplates(): Promise<SyncResult> {
        let totalTemplates = 0
        let createdCount = 0
        let updatedCount = 0
        let skippedCount = 0
        let errorCount = 0

        logger.info('Starting HogFunction template sync...')

        // Process all templates
        for (const template of HOG_FUNCTION_TEMPLATES_FOR_TESTS) {
            try {
                totalTemplates++
                const result = await this.processTemplate(template)

                if (result === 'created') {
                    createdCount++
                } else if (result === 'updated') {
                    updatedCount++
                } else if (result === 'skipped') {
                    skippedCount++
                }
            } catch (error) {
                errorCount++
                logger.error('Error syncing template to database', {
                    template_id: template.id,
                    error: String(error),
                    stack: error.stack,
                })
            }
        }

        const result = {
            totalTemplates,
            createdCount,
            updatedCount,
            skippedCount,
            errorCount,
        }

        logger.info(`Template sync completed`, result)

        return result
    }

    /**
     * Process a single template
     */
    public async processTemplate(template: HogFunctionTemplate): Promise<'created' | 'updated' | 'skipped'> {
        const sha = this.generateShaFromTemplate(template)

        // Check if template already exists with the same SHA (exactly the same content)
        const existingTemplateWithSameSha = await this.db.query(
            PostgresUse.COMMON_READ,
            `SELECT id FROM posthog_hogfunctiontemplate WHERE template_id = $1 AND sha = $2`,
            [template.id, sha],
            'templateSyncCheck'
        )

        if (existingTemplateWithSameSha.rows.length > 0) {
            logger.debug('Template exists with same SHA, skipping', { template_id: template.id, sha })
            return 'skipped'
        }

        // Determine code language type
        const codeLanguage = this.isJavaScriptSourceType(template.type) ? 'javascript' : 'hog'

        // Compile bytecode for Hog templates
        let bytecode = null
        if (codeLanguage === 'hog') {
            try {
                bytecode = await compileHog(template.hog)
            } catch (error) {
                logger.error('Failed to compile template bytecode', {
                    template_id: template.id,
                    error: String(error),
                })
            }
        }

        // Convert mappings to JSON
        const mappings = template.mappings ? template.mappings.map((mapping) => JSON.stringify(mapping)) : null

        // Convert mapping_templates to JSON
        const mappingTemplates = template.mapping_templates
            ? template.mapping_templates.map((mappingTemplate) => JSON.stringify(mappingTemplate))
            : null

        // Fetch existing template ID if it exists
        let templateId: string | null = null
        const existingTemplate = await this.db.query(
            PostgresUse.COMMON_READ,
            `SELECT id FROM posthog_hogfunctiontemplate WHERE template_id = $1`,
            [template.id],
            'templateSyncExists'
        )

        if (existingTemplate.rows.length > 0) {
            templateId = existingTemplate.rows[0].id
        }

        // Prepare common template data
        const templateData = {
            id: templateId || new UUIDT().toString(),
            template_id: template.id,
            sha,
            name: template.name,
            description: template.description,
            code: template.hog,
            code_language: codeLanguage,
            inputs_schema: template.inputs_schema,
            bytecode,
            type: template.type,
            status: template.status,
            category: template.category,
            free: template.free,
            icon_url: template.icon_url || null,
            filters: template.filters || null,
            masking: template.masking || null,
            mappings,
            mapping_templates: mappingTemplates,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        }

        try {
            if (existingTemplate.rows.length > 0) {
                // Update existing template with on conflict handling
                await this.db.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_hogfunctiontemplate SET 
                        sha = $1,
                        name = $2,
                        description = $3,
                        code = $4,
                        code_language = $5,
                        inputs_schema = $6,
                        bytecode = $7,
                        type = $8,
                        status = $9,
                        category = $10,
                        free = $11,
                        icon_url = $12,
                        filters = $13,
                        masking = $14,
                        mappings = $15,
                        mapping_templates = $16,
                        updated_at = $17
                    WHERE template_id = $18`,
                    [
                        sha,
                        templateData.name,
                        templateData.description,
                        templateData.code,
                        templateData.code_language,
                        JSON.stringify(templateData.inputs_schema),
                        JSON.stringify(templateData.bytecode),
                        templateData.type,
                        templateData.status,
                        JSON.stringify(templateData.category),
                        templateData.free,
                        templateData.icon_url,
                        templateData.filters ? JSON.stringify(templateData.filters) : null,
                        templateData.masking ? JSON.stringify(templateData.masking) : null,
                        templateData.mappings ? JSON.stringify(templateData.mappings) : null,
                        templateData.mapping_templates ? JSON.stringify(templateData.mapping_templates) : null,
                        templateData.updated_at,
                        template.id,
                    ],
                    'templateSyncUpdate'
                )
                logger.info('Updated template', { template_id: template.id })
                return 'updated'
            } else {
                // Create new template
                await insertRow(this.db, 'posthog_hogfunctiontemplate', templateData)
                logger.info('Created template', { template_id: template.id })
                return 'created'
            }
        } catch (error) {
            logger.error('Error inserting/updating template', {
                template_id: template.id,
                error: String(error),
                stack: error.stack,
            })
            throw error
        }
    }

    /**
     * Generate a SHA hash for template content - matching Python implementation
     */
    private generateShaFromTemplate(template: HogFunctionTemplate): string {
        const codeLanguage = this.isJavaScriptSourceType(template.type) ? 'javascript' : 'hog'

        // Create a dict structure matching the Python implementation
        const templateDict = {
            id: template.id,
            code: template.hog,
            code_language: codeLanguage,
            inputs_schema: template.inputs_schema,
            status: template.status,
            mappings: template.mappings ? template.mappings.map((m) => JSON.stringify(m)) : null,
            mapping_templates: template.mapping_templates
                ? template.mapping_templates.map((mt) => JSON.stringify(mt))
                : null,
            filters: template.filters,
        }

        // Generate content hash - sort keys to ensure consistent output
        const contentForHash = JSON.stringify(templateDict, Object.keys(templateDict).sort())

        // Generate SHA1 hash and take first 8 characters (same as Python)
        return crypto.createHash('sha1').update(contentForHash).digest('hex').substring(0, 8)
    }

    /**
     * Check if template type requires JavaScript source
     */
    private isJavaScriptSourceType(type: string): boolean {
        return ['site_destination', 'site_app'].includes(type)
    }
}

export interface SyncResult {
    totalTemplates: number
    createdCount: number
    updatedCount: number
    skippedCount: number
    errorCount: number
}
