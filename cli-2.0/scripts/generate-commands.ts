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
  
  // Build API call from enhanced mapping data
  const apiCall = buildAPICallFromMapping(toolInfo, projectId, params)
  
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

// Build API call from enhanced mapping information
function buildAPICallFromMapping(toolInfo: any, projectId: string, params: any) {
  let endpoint = toolInfo.endpoint || '/api/unknown'
  let method = toolInfo.method || 'GET'
  
  // Replace template placeholders
  // Check if ID is required but missing
  if (endpoint.includes('{id}') && !params.id) {
    throw new Error('ID parameter required for this command. Use --id <value>')
  }
  
  endpoint = endpoint
    .replace(/\\\{project_id\\\}/g, projectId)
    .replace(/\\\{id\\\}/g, params.id || '')
    // Handle the literal string case
    .replace('\${encodeURIComponent(String(projectId))}', encodeURIComponent(String(projectId)))
  
  const apiCall: any = {
    method: method as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: endpoint
  }
  
  // Add request body/query based on method
  if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
    if (params.id) {
      const { id, ...data } = params
      apiCall.body = data
    } else {
      apiCall.body = params
    }
  } else if (method === 'GET' && Object.keys(params).length > 0) {
    // For GET requests, add query parameters (excluding id which is in path)
    const { id, ...queryParams } = params
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
