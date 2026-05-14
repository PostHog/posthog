#!/usr/bin/env tsx
/**
 * Generates CLI commands from MCP tool definitions.
 *
 * Reads tool-definitions-all.json and generates CLI command handlers
 * for each tool with proper command grouping.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const CLI_ROOT = path.resolve(__dirname, '..')
const MCP_ROOT = path.resolve(CLI_ROOT, '../services/mcp')
const SCHEMA_FILE = path.resolve(MCP_ROOT, 'schema/tool-definitions-all.json')
const COMMAND_MAPPINGS_FILE = path.resolve(CLI_ROOT, 'schema/command-mappings.json')
const GENERATED_DIR = path.resolve(CLI_ROOT, 'src/generated')

interface ToolDefinition {
    description: string
    category: string
    feature: string
    summary: string
    title: string
    required_scopes: string[]
    new_mcp: boolean
    annotations: {
        destructiveHint: boolean
        idempotentHint: boolean
        openWorldHint: boolean
        readOnlyHint: boolean
    }
}

interface CommandMapping {
    commands: Record<
        string,
        {
            aliases: string[]
            description: string
            subcommands: Record<
                string,
                {
                    mcp_tool: string
                    description: string
                    aliases?: string[]
                }
            >
        }
    >
    product_groups: Record<
        string,
        {
            name: string
            description: string
            commands: string[]
        }
    >
}

// No longer needed - MCP tools handle their own API mappings

function loadDefinitions(): Record<string, ToolDefinition> {
    const content = fs.readFileSync(SCHEMA_FILE, 'utf8')
    return JSON.parse(content)
}

function loadCommandMappings(): CommandMapping {
    const content = fs.readFileSync(COMMAND_MAPPINGS_FILE, 'utf8')
    return JSON.parse(content)
}

function loadEnhancedMappings(): any {
    const enhancedFile = path.resolve(CLI_ROOT, 'schema/command-mappings-enhanced.json')
    if (!fs.existsSync(enhancedFile)) {
        throw new Error('Enhanced mappings not found. Run: pnpm generate:commands')
    }
    const content = fs.readFileSync(enhancedFile, 'utf8')
    return JSON.parse(content)
}

// This function is no longer needed - we import MCP tools directly

function generateCommandsFile(): void {
    const definitions = loadDefinitions()
    const enhancedMappings = loadEnhancedMappings()

    // Create generated directory
    if (!fs.existsSync(GENERATED_DIR)) {
        fs.mkdirSync(GENERATED_DIR, { recursive: true })
    }

    // Validate that all mapped MCP tools exist
    const missingTools: string[] = []
    for (const [commandName, command] of Object.entries(enhancedMappings.commands)) {
        for (const [subcommandName, subcommand] of Object.entries(command.subcommands)) {
            if (!definitions[subcommand.mcp_tool]) {
                missingTools.push(`${commandName}.${subcommandName} -> ${subcommand.mcp_tool}`)
            }
        }
    }

    if (missingTools.length > 0) {
        console.warn('⚠️  Warning: Some mapped MCP tools do not exist:')
        missingTools.forEach((tool) => console.warn(`   ${tool}`))
    }

    // Generate the commands file
    const commandsContent = `// Auto-generated CLI commands from command mappings
// Do not edit manually - run 'npm run generate:commands' to regenerate

import type { Context } from '../mcp-context.js'

interface SubCommand {
  name: string
  humanName: string
  description: string
  category: string
  endpoint?: string
  method?: string
  inputs: any
  mcp_tool: string
  aliases?: string[]
}

interface Command {
  aliases?: string[]
  description: string
  subcommands: Record<string, SubCommand>
}

interface ProductGroup {
  name: string
  description: string
  commands: string[]
}

// Human-readable command structure
export const commands: Record<string, Command> = ${JSON.stringify(enhancedMappings.commands, null, 2)}

// Enhanced mappings metadata
export const enhancedMappingsMeta = {
  version: '${enhancedMappings.version}',
  generated_at: '${enhancedMappings.generated_at}',
  stats: ${JSON.stringify(enhancedMappings.stats, null, 2)}
}

// Execute a command by resolving human-readable name to MCP tool
export async function executeCommand(context: Context, commandName: string, subcommandName: string, params: any) {
  const command = commands[commandName]
  if (!command) {
    throw new Error('Unknown command: ' + commandName)
  }
  
  const subcommand = command.subcommands[subcommandName]
  if (!subcommand) {
    throw new Error('Unknown subcommand: ' + commandName + ' ' + subcommandName)
  }
  
  return await executeToolCall(context, subcommand.mcp_tool, params)
}

// Execute tool using enhanced mapping information
export async function executeToolCall(context: Context, toolName: string, params: any) {
  const projectId = await context.stateManager.getProjectId()
  
  // Find tool information from enhanced mappings
  const toolInfo = findToolInEnhancedMappings(toolName)
  
  if (!toolInfo) {
    throw new Error('Tool not found in enhanced mappings: ' + toolName)
  }
  
  const resolvedParams = await resolveCustomPathParams(context, toolName, projectId, params)

  // Build API call from enhanced mapping data. Some MCP tools are wrappers or
  // hand-written helpers, so their endpoint cannot be scraped from generated
  // tool files. Keep those explicit here instead of falling back to /api/unknown.
  const apiCall = buildCustomAPICall(toolName, projectId, resolvedParams) ?? buildAPICallFromMapping(toolInfo, projectId, resolvedParams)
  
  return await context.api.request(apiCall)
}

// Find tool information from enhanced mappings
function findToolInEnhancedMappings(toolName: string): any | null {
  for (const [commandName, command] of Object.entries(commands)) {
    for (const [subcommandName, subcommand] of Object.entries(command.subcommands)) {
      if (subcommand.mcp_tool === toolName) {
        return subcommand
      }
    }
  }
  
  return null
}

function compactObject(value: Record<string, any>) {
  return Object.fromEntries(Object.entries(value).filter(([, entryValue]) => entryValue !== undefined && entryValue !== null))
}

function hasExplicitShortId(params: any) {
  return params.short_id !== undefined || params.shortId !== undefined || params['short-id'] !== undefined
}

async function resolveShortIdFromList(context: Context, params: any, listPath: string) {
  if (!params.id || hasExplicitShortId(params)) {
    return params
  }

  const listResult = await context.api.request<any>({ method: 'GET', path: listPath })
  const rows = Array.isArray(listResult) ? listResult : listResult?.results
  const matchingRow = Array.isArray(rows) ? rows.find((row) => String(row?.id) === String(params.id)) : undefined

  if (!matchingRow?.short_id) {
    return params
  }

  return { ...params, short_id: matchingRow.short_id }
}

async function resolveCustomPathParams(context: Context, toolName: string, projectId: string, params: any) {
  switch (toolName) {
    case 'notebooks-retrieve':
      return await resolveShortIdFromList(context, params, '/api/projects/' + projectId + '/notebooks/')

    case 'session-recording-playlist-get':
      return await resolveShortIdFromList(context, params, '/api/projects/' + projectId + '/session_recording_playlists/')

    default:
      return params
  }
}

// Build API calls for wrapper or hand-written MCP tools that do not expose a
// scrapeable context.api.request({ method, path }) block.
function buildCustomAPICall(toolName: string, projectId: string, params: any) {
  switch (toolName) {
    case 'evaluations-get':
      return {
        method: 'GET' as const,
        path: '/api/environments/' + projectId + '/evaluations/',
        query: compactObject({
          enabled: params.enabled,
          id__in: params.id__in,
          limit: params.limit,
          offset: params.offset,
          order_by: params.order_by,
          search: params.search,
        }),
      }

    case 'evaluation-get': {
      const id = readPathParam(params, 'id', true)
      if (id === undefined || id === null || String(id).length === 0) {
        throw new Error('id parameter required for this command. Use --id <value>')
      }
      return {
        method: 'GET' as const,
        path: '/api/environments/' + projectId + '/evaluations/' + encodeURIComponent(String(id)) + '/',
      }
    }

    case 'event-definitions-list':
      return {
        method: 'GET' as const,
        path: '/api/projects/' + projectId + '/event_definitions/',
        query: compactObject({
          search: params.q ?? params.search,
          limit: params.limit,
          offset: params.offset,
        }),
      }

    case 'experiment-get-all':
      return {
        method: 'GET' as const,
        path: '/api/projects/' + projectId + '/experiments/',
        query: compactObject(params),
      }

    case 'hogql-schema':
      return {
        method: 'POST' as const,
        path: '/api/projects/' + projectId + '/query/',
        body: { query: compactObject({ kind: 'DatabaseSchemaQuery', connectionId: params.connectionId }) },
      }

    case 'projects-get':
      return { method: 'GET' as const, path: '/api/projects/', query: compactObject(params) }

    case 'property-definitions':
    case 'properties-list': {
      const type = params.type ?? 'event'
      return {
        method: 'GET' as const,
        path: '/api/projects/' + projectId + '/property_definitions/',
        query: compactObject({
          event_names: params.eventName ? JSON.stringify([params.eventName]) : undefined,
          exclude_core_properties: params.includePredefinedProperties === undefined ? undefined : !params.includePredefinedProperties,
          filter_by_event_names: type === 'event' && params.eventName ? true : undefined,
          is_feature_flag: false,
          limit: params.limit,
          offset: params.offset,
          type,
          exclude_hidden: true,
        }),
      }
    }

    case 'query-session-recordings-list':
      return {
        method: 'POST' as const,
        path: '/api/projects/' + projectId + '/query/',
        body: { query: compactObject({ kind: 'RecordingsQuery', ...params }) },
      }

    case 'user-get':
      return {
        method: 'GET' as const,
        path: '/api/users/' + encodeURIComponent(String(params.uuid ?? params.id ?? '@me')) + '/',
      }

    case 'user-home-settings-get':
      return {
        method: 'GET' as const,
        path: '/api/user_home_settings/' + encodeURIComponent(String(params.uuid ?? params.id ?? '@me')) + '/',
      }

    default:
      return null
  }
}

function camelCase(value: string) {
  return value.replace(/[_-]([a-z])/g, (_match, letter) => String(letter).toUpperCase())
}

function readPathParam(params: any, placeholder: string, canUseIdFallback: boolean) {
  const camel = camelCase(placeholder)
  const dashed = placeholder.replace(/_/g, '-')
  const exactValue = params[placeholder] ?? params[camel] ?? params[dashed]
  if (exactValue !== undefined) {
    return exactValue
  }
  return placeholder === 'id' || canUseIdFallback ? params.id : undefined
}

function omitPathParams(params: any, pathParams: Set<string>) {
  const queryParams = { ...params }
  delete queryParams.id
  for (const pathParam of pathParams) {
    delete queryParams[pathParam]
    delete queryParams[camelCase(pathParam)]
    delete queryParams[pathParam.replace(/_/g, '-')]
  }
  return queryParams
}

// Build API call from enhanced mapping information
function buildAPICallFromMapping(toolInfo: any, projectId: string, params: any) {
  let endpoint = toolInfo.endpoint || '/api/unknown'
  let method = toolInfo.method || 'GET'
  const pathParams = new Set<string>()
  
  endpoint = endpoint
    .replace(/\\\{project_id\\\}/g, projectId)
    .replace(/\\\{org_id\\\}/g, '@current')
    // Handle the literal string case
    .replace('\${encodeURIComponent(String(projectId))}', encodeURIComponent(String(projectId)))

  const pathParamNames = Array.from(String(endpoint).matchAll(/\\\{([^}]+)\\\}/g), (match: RegExpMatchArray) => match[1])
  const canUseIdFallback = pathParamNames.length === 1

  endpoint = endpoint.replace(/\\\{([^}]+)\\\}/g, (_match: string, placeholder: string) => {
    const value = readPathParam(params, placeholder, canUseIdFallback)
    if (value === undefined || value === null || String(value).length === 0) {
      throw new Error(placeholder + ' parameter required for this command. Use --' + placeholder.replace(/_/g, '-') + ' <value>')
    }
    pathParams.add(placeholder)
    return encodeURIComponent(String(value))
  })
  
  const apiCall: any = {
    method: method as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: endpoint
  }
  
  // Add request body/query based on method
  if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
    apiCall.body = omitPathParams(params, pathParams)
  } else if (method === 'GET' && Object.keys(params).length > 0) {
    // For GET requests, add query parameters excluding path params.
    const queryParams = omitPathParams(params, pathParams)
    if (Object.keys(queryParams).length > 0) {
      apiCall.query = queryParams
    }
  }
  
  
  return apiCall
}

`

    fs.writeFileSync(path.join(GENERATED_DIR, 'commands.ts'), commandsContent)
    console.log('✅ Generated commands.ts')
    console.log('📊 Commands:', Object.keys(enhancedMappings.commands).join(', '))
    console.log('📋 Enhanced mappings version:', enhancedMappings.version)
    console.log(
        '🔗 Total MCP tool mappings:',
        Object.values(enhancedMappings.commands).reduce((acc, cmd) => acc + Object.keys(cmd.subcommands).length, 0)
    )
}

function main() {
    console.log('🔧 Generating CLI commands from MCP tool definitions...')
    try {
        generateCommandsFile()
        console.log('🎉 Done!')
    } catch (error) {
        console.error('❌ Failed to generate commands:', error.message)
        process.exit(1)
    }
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main()
}
