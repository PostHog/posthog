#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * Dashboard widget config Zod codegen (product-scoped caller).
 *
 * Flow:
 * 1. Slice the widget catalog op with filterSchemaByOperationIds(..., { includeResponseSchemas: true })
 * 2. Orval 8.14+ with generateReusableSchemas — reusable Zod per OpenAPI component
 * 3. Copy transitive *WidgetConfig deps into generated/widget-config-schemas/
 * 4. Barrel widget-configs.zod.ts — friendly re-exports, types, form `.pick()` schemas
 */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
    annotatePureZodExports,
    discoverCatalogEntryConfigPropertyKeys,
    discoverComponentSchemaNames,
    filterSchemaByOperationIds,
    fixNullDefaults,
    preprocessSchema,
    resolveNestedRefs,
    runOrvalParallel,
} from '../../../../tools/openapi-codegen/index.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const dashboardsGeneratedDir = path.resolve(__dirname, '../generated')
const widgetConfigSchemasDir = path.join(dashboardsGeneratedDir, 'widget-config-schemas')
const repoRoot = path.resolve(__dirname, '../../../..')
const frontendRoot = path.resolve(repoRoot, 'frontend')
const schemaPath = process.env.OPENAPI_SCHEMA_PATH
    ? path.resolve(frontendRoot, process.env.OPENAPI_SCHEMA_PATH)
    : path.resolve(frontendRoot, 'tmp', 'openapi.json')

const WIDGET_CATALOG_OPERATION_ID = 'dashboards_widget_catalog_retrieve'
const WIDGET_FILTER_ENTRY_MODEL = 'WidgetFilterEntry'
const FORM_FIELDS_JSON = path.join(dashboardsGeneratedDir, 'widget-form-fields.json')
const SCHEMAS_SUBDIR_NAME = 'widget-config-schemas'

function lowerFirst(value) {
    return value.charAt(0).toLowerCase() + value.slice(1)
}

/** Orval reusable-schema filename for a component schema name. */
function componentNameToOrvalSchemaFile(componentName) {
    return `${lowerFirst(componentName)}.zod.ts`
}

/** Map OpenAPI component name → friendly FE export (errorTrackingWidgetConfigSchema, …). */
function configModelNameToFriendlyNames(configModelName) {
    let typeName = configModelName
    if (configModelName.endsWith('ListWidgetConfig')) {
        typeName = configModelName.replace('ListWidgetConfig', 'WidgetConfig')
    } else if (!configModelName.endsWith('WidgetConfig')) {
        console.error(`Unexpected config model name ${configModelName}; expected *WidgetConfig`)
        process.exit(1)
    }

    return {
        type: typeName,
        schema: `${lowerFirst(typeName)}Schema`,
        orvalExport: configModelName,
    }
}

function getCatalogSlice(fullSchema) {
    return filterSchemaByOperationIds(fullSchema, new Set([WIDGET_CATALOG_OPERATION_ID]), {
        includeResponseSchemas: true,
    })
}

const CATALOG_ENTRY_MARKERS = {
    entrySuffix: 'CatalogEntryOpenApi',
    typeField: 'widget_type',
    configField: 'config_schema',
}

function writeConfigPropertyKeysJson(catalogSlice) {
    const { propertyKeys, propertyTrees } = discoverCatalogEntryConfigPropertyKeys(catalogSlice, {
        ...CATALOG_ENTRY_MARKERS,
        includePropertyTrees: true,
    })
    if (Object.keys(propertyKeys).length === 0) {
        console.error(`No catalog entry config property maps found for ${WIDGET_CATALOG_OPERATION_ID}.`)
        process.exit(1)
    }
    const outputPath = path.join(dashboardsGeneratedDir, 'widget-config-property-keys.json')
    fs.writeFileSync(
        outputPath,
        `${JSON.stringify({ configPropertyKeys: propertyKeys, configPropertyTrees: propertyTrees }, null, 4)}\n`
    )
    console.log(
        `   ✓ widget-config-property-keys → ${path.relative(repoRoot, outputPath)} (${Object.keys(propertyKeys).length} types)`
    )
}

function readFormFieldsManifest() {
    if (!fs.existsSync(FORM_FIELDS_JSON)) {
        console.error(`Missing ${FORM_FIELDS_JSON}. Run hogli build:widget-types first.`)
        process.exit(1)
    }
    return JSON.parse(fs.readFileSync(FORM_FIELDS_JSON, 'utf-8')).widgets ?? {}
}

function collectTransitiveComponentNames(catalogSlice, rootComponentNames) {
    const allSchemas = catalogSlice.components?.schemas ?? {}
    const refs = new Set(rootComponentNames.map((name) => `#/components/schemas/${name}`))
    const allRefs = resolveNestedRefs(allSchemas, refs)
    return [...allRefs]
        .map((ref) => ref.replace('#/components/schemas/', ''))
        .filter((name) => allSchemas[name])
        .sort()
}

function copyOrvalSchemaFiles(orvalSchemasDir, componentNames) {
    fs.rmSync(widgetConfigSchemasDir, { recursive: true, force: true })
    fs.mkdirSync(widgetConfigSchemasDir, { recursive: true })

    const copied = []
    for (const componentName of componentNames) {
        const fileName = componentNameToOrvalSchemaFile(componentName)
        const sourcePath = path.join(orvalSchemasDir, fileName)
        if (!fs.existsSync(sourcePath)) {
            console.warn(`   ⚠ skipping ${componentName}: no Orval schema file ${fileName}`)
            continue
        }

        const destPath = path.join(widgetConfigSchemasDir, fileName)
        fs.copyFileSync(sourcePath, destPath)
        fixNullDefaults(destPath)
        annotatePureZodExports(destPath)
        copied.push({ componentName, fileName })
    }

    if (copied.length === 0) {
        console.error('Orval produced no reusable widget config schema files.')
        process.exit(1)
    }

    return copied
}

function buildBarrelImports(copiedSchemas, configModelNames) {
    const importLines = []
    const aliasLines = []

    const exportedComponentNames = new Set([...configModelNames, WIDGET_FILTER_ENTRY_MODEL])
    // When the friendly type export matches the Orval component name (config models without a
    // "List" infix), the import must be aliased or it collides with the exported type.
    const friendlyTypeNames = new Set(configModelNames.map((name) => configModelNameToFriendlyNames(name).type))
    const importLocalName = (componentName) =>
        friendlyTypeNames.has(componentName) ? `${componentName}Component` : componentName

    for (const { componentName, fileName } of copiedSchemas) {
        if (!exportedComponentNames.has(componentName)) {
            continue
        }
        const importPath = `./${SCHEMAS_SUBDIR_NAME}/${fileName.replace(/\.ts$/, '')}`
        const localName = importLocalName(componentName)
        const importSpecifier = localName === componentName ? componentName : `${componentName} as ${localName}`
        importLines.push(`import { ${importSpecifier} } from '${importPath}'`)
    }

    for (const configModelName of configModelNames) {
        const { schema, orvalExport } = configModelNameToFriendlyNames(configModelName)
        aliasLines.push(`export const ${schema} = /* @__PURE__ */ ${importLocalName(orvalExport)}`)
    }

    const filterEntryImport = copiedSchemas.find((entry) => entry.componentName === WIDGET_FILTER_ENTRY_MODEL)
    if (filterEntryImport) {
        aliasLines.push(`export const widgetFilterEntrySchema = /* @__PURE__ */ ${WIDGET_FILTER_ENTRY_MODEL}`)
    }

    return { importLines, aliasLines }
}

function buildZodModuleFooter(configModelNames, formFieldsManifest) {
    const typeExports = []
    let firstConfigTypeExport = null

    for (const configModelName of configModelNames) {
        const { type, schema } = configModelNameToFriendlyNames(configModelName)
        if (firstConfigTypeExport === null) {
            firstConfigTypeExport = type
        }
        typeExports.push(`export type ${type} = zod.infer<typeof ${schema}>`)
    }

    const widgetFiltersRecordType = `NonNullable<${firstConfigTypeExport}['widgetFilters']>`
    const filterTypeExports = [
        `type WidgetFiltersRecord = ${widgetFiltersRecordType}`,
        'export type WidgetFilterConfigEntry = WidgetFiltersRecord[string]',
        'export type WidgetFilterConfigRecord = WidgetFiltersRecord',
        'export type StoredWidgetFilter = WidgetFilterConfigEntry',
    ]

    const formExports = []
    for (const widgetManifest of Object.values(formFieldsManifest)) {
        const pickEntries = widgetManifest.formFields.map((field) => `    ${field}: true,`).join('\n')
        formExports.push(
            `export const ${widgetManifest.formSchemaExport} = ${widgetManifest.configSchemaExport}.pick({`,
            pickEntries,
            '})',
            ''
        )
    }

    return [...typeExports, '', ...filterTypeExports, '', ...formExports].join('\n')
}

async function runOrvalOnCatalogSlice(catalogSlice) {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'widget-config-orval-'))
    const inputFile = path.join(tmpDir, 'catalog.json')
    const orvalSchemasDir = path.join(tmpDir, 'schemas')
    const targetFile = path.join(tmpDir, 'catalog.zod.ts')
    fs.writeFileSync(inputFile, JSON.stringify(catalogSlice))

    const results = await runOrvalParallel([
        {
            label: 'widget-catalog',
            config: {
                input: inputFile,
                output: {
                    target: targetFile,
                    mode: 'split',
                    client: 'zod',
                    prettier: false,
                    schemas: orvalSchemasDir,
                    override: {
                        zod: {
                            generate: {
                                param: false,
                                query: false,
                                header: false,
                                body: false,
                                response: true,
                            },
                            generateReusableSchemas: true,
                        },
                    },
                },
            },
        },
    ])

    const rejected = results.find((result) => result.status === 'rejected')
    if (rejected) {
        console.error(`Orval widget catalog generation failed: ${rejected.reason?.message ?? rejected.reason}`)
        process.exit(1)
    }

    return orvalSchemasDir
}

async function main() {
    if (!fs.existsSync(schemaPath)) {
        console.error(`OpenAPI schema not found at ${schemaPath}. Run hogli build:openapi-schema first.`)
        process.exit(1)
    }

    const fullSchema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'))
    const catalogSlice = preprocessSchema(getCatalogSlice(fullSchema))
    writeConfigPropertyKeysJson(catalogSlice)

    const configModelNames = discoverComponentSchemaNames(catalogSlice, { nameSuffix: 'WidgetConfig' })
    if (configModelNames.length === 0) {
        console.error(
            `No *WidgetConfig schemas in the OpenAPI slice for ${WIDGET_CATALOG_OPERATION_ID}. ` +
                'Regenerate hogli build:openapi-schema.'
        )
        process.exit(1)
    }

    const transitiveComponentNames = collectTransitiveComponentNames(catalogSlice, [
        ...configModelNames,
        WIDGET_FILTER_ENTRY_MODEL,
    ])

    console.log('Generating dashboard widget config Zod schemas via Orval (generateReusableSchemas)...')
    const orvalSchemasDir = await runOrvalOnCatalogSlice(catalogSlice)
    const copiedSchemas = copyOrvalSchemaFiles(orvalSchemasDir, transitiveComponentNames)

    // The barrel imports and aliases below assume every config model and the filter entry were
    // copied — a missing Orval file would otherwise produce a barrel referencing undefined symbols.
    const copiedNames = new Set(copiedSchemas.map((entry) => entry.componentName))
    const missingRequired = [...configModelNames, WIDGET_FILTER_ENTRY_MODEL].filter((name) => !copiedNames.has(name))
    if (missingRequired.length > 0) {
        console.error(`Orval did not emit schema files for required components: ${missingRequired.join(', ')}`)
        process.exit(1)
    }

    const outputFile = path.join(dashboardsGeneratedDir, 'widget-configs.zod.ts')
    fs.mkdirSync(dashboardsGeneratedDir, { recursive: true })

    const { importLines, aliasLines } = buildBarrelImports(copiedSchemas, configModelNames)
    const formFieldsManifest = readFormFieldsManifest()
    const footer = buildZodModuleFooter(configModelNames, formFieldsManifest)

    const header = `/** Auto-generated from products/dashboards/backend/widget_specs — do not edit.
 * Regenerate: hogli build:widget-types
 */
import { z as zod } from 'zod'
`

    fs.writeFileSync(outputFile, `${header}${importLines.join('\n')}\n\n${aliasLines.join('\n')}\n\n${footer}`)

    execSync(`pnpm exec oxfmt ${outputFile} ${widgetConfigSchemasDir}`, {
        stdio: 'pipe',
        cwd: repoRoot,
    })
    console.log(
        `   ✓ dashboards:widget-config-zod → ${path.relative(repoRoot, outputFile)} (${copiedSchemas.length} Orval schema files)`
    )
}

await main()
