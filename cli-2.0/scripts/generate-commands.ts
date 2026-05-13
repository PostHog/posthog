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

// No longer needed - MCP tools handle their own API mappings

function loadDefinitions(): Record<string, ToolDefinition> {
  const content = fs.readFileSync(SCHEMA_FILE, 'utf8')
  return JSON.parse(content)
}

// This function is no longer needed - we import MCP tools directly

function generateCommandsFile(): void {
  const definitions = loadDefinitions()
  
  // Create generated directory
  if (!fs.existsSync(GENERATED_DIR)) {
    fs.mkdirSync(GENERATED_DIR, { recursive: true })
  }
  
  const commandGroups: Record<string, { tools: Array<{ name: string, description?: string }> }> = {}
  
  // Group tools by feature - all tools are included since MCP tools handle their own endpoints
  for (const [toolName, tool] of Object.entries(definitions)) {
    const feature = tool.feature.toLowerCase().replace(/\s+/g, '-')
    
    // Initialize feature group if not exists
    if (!commandGroups[feature]) {
      commandGroups[feature] = { tools: [] }
    }
    
    // Add all tools since they will be handled by MCP tool imports
    commandGroups[feature].tools.push({
      name: toolName,
      description: tool.summary || tool.description
    })
  }
  
  // Generate the commands file
  const allToolNames = Object.keys(definitions)
  const commandsContent = `// Auto-generated CLI commands from MCP tool definitions
// Do not edit manually - run 'npm run generate:commands' to regenerate

import type { Context } from '../mcp-context.js'

// Command group definitions
export const commandGroups = ${JSON.stringify(commandGroups, null, 2)}

// Simple API call based on tool name and common patterns
export async function executeToolCall(context: Context, toolName: string, params: any) {
  const projectId = await context.stateManager.getProjectId()
  
  // Extract the HTTP method and resource from tool name using simple patterns
  const apiCall = getApiCallFromToolName(toolName, projectId, params)
  
  if (!apiCall) {
    throw new Error(\`Unable to determine API call for tool: \${toolName}\`)
  }
  
  return await context.api.request(apiCall)
}

// Extract API call info from tool name using the same patterns MCP tools use
function getApiCallFromToolName(toolName: string, projectId: string, params: any) {
  // Common patterns found in MCP tools:
  if (toolName.includes('list') || toolName.includes('get-all')) {
    const resource = extractResource(toolName)
    return {
      method: 'GET' as const,
      path: \`/api/projects/\${projectId}/\${resource}/\`,
      query: { limit: params.limit, offset: params.offset, search: params.search }
    }
  }
  
  if (toolName.includes('create')) {
    const resource = extractResource(toolName)
    return {
      method: 'POST' as const,
      path: \`/api/projects/\${projectId}/\${resource}/\`,
      body: params
    }
  }
  
  if (toolName.includes('retrieve') || toolName.includes('get')) {
    const resource = extractResource(toolName)
    if (!params.id) throw new Error('ID required for retrieve operations')
    return {
      method: 'GET' as const,
      path: \`/api/projects/\${projectId}/\${resource}/\${params.id}/\`,
    }
  }
  
  if (toolName.includes('update') || toolName.includes('partial-update')) {
    const resource = extractResource(toolName)
    if (!params.id) throw new Error('ID required for update operations')
    const { id, ...body } = params
    return {
      method: 'PATCH' as const,
      path: \`/api/projects/\${projectId}/\${resource}/\${id}/\`,
      body
    }
  }
  
  if (toolName.includes('delete') || toolName.includes('destroy')) {
    const resource = extractResource(toolName)
    if (!params.id) throw new Error('ID required for delete operations')
    return {
      method: 'DELETE' as const,
      path: \`/api/projects/\${projectId}/\${resource}/\${params.id}/\`,
    }
  }
  
  return null
}

// Extract resource name from tool name
function extractResource(toolName: string): string {
  // Handle special cases with exact mappings
  const resourceMap: Record<string, string> = {
    'feature-flag': 'feature_flags',
    'feature_flag': 'feature_flags',
    'batch-export': 'batch_exports',
    'early-access-feature': 'early_access_features',
    'experiment': 'experiments',
    'cohort': 'cohorts',
    'dashboard': 'dashboards',
    'insight': 'insights',
    'action': 'actions',
    'survey': 'surveys',
    'notebook': 'notebooks'
  }
  
  // Try exact matches first
  for (const [key, value] of Object.entries(resourceMap)) {
    if (toolName.includes(key)) {
      return value
    }
  }
  
  // Pattern-based extraction for common naming patterns
  const parts = toolName.split('-')
  
  // Common action verbs that appear at the start
  const actionVerbs = ['create', 'update', 'delete', 'get', 'list', 'retrieve', 'destroy', 'partial']
  
  // Pattern: {action}-{resource} (e.g., "create-webhook", "delete-team")
  if (parts.length >= 2 && actionVerbs.includes(parts[0])) {
    const resource = parts.slice(1).join('-')
    return resource.endsWith('s') ? resource : resource + 's'
  }
  
  // Pattern: {resource}-{action} or {resource}s-{action} (e.g., "cohort-create", "actions-get-all")
  if (parts.length >= 2 && actionVerbs.includes(parts[parts.length - 1])) {
    const resource = parts.slice(0, -1).join('-')
    return resource.endsWith('s') ? resource : resource + 's'
  }
  
  // Pattern: {resource}-{action}-{modifier} (e.g., "logs-alerts-create")
  if (parts.length >= 3 && actionVerbs.includes(parts[parts.length - 2])) {
    const resource = parts.slice(0, -2).join('-')
    return resource.endsWith('s') ? resource : resource + 's'
  }
  
  // Fallback: assume first part is the resource (for tools like "activity-log-list")
  const firstPart = parts[0]
  return firstPart.endsWith('s') ? firstPart : firstPart + 's'
}
`

  fs.writeFileSync(path.join(GENERATED_DIR, 'commands.ts'), commandsContent)
  console.log('✅ Generated commands.ts with', allToolNames.length, 'tools')
  console.log('📊 Command groups:', Object.keys(commandGroups).join(', '))
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