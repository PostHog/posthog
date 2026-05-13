#!/usr/bin/env tsx
/**
 * Command mappings generator that extracts actual API endpoints and parameters
 * from the generated MCP tools to create a comprehensive CLI mapping.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const CLI_ROOT = path.resolve(__dirname, '..')
const MCP_ROOT = path.resolve(CLI_ROOT, '../services/mcp')
const TOOL_DEFINITIONS_FILE = path.resolve(MCP_ROOT, 'schema/tool-definitions-all.json')
const TOOL_INPUTS_FILE = path.resolve(MCP_ROOT, 'schema/tool-inputs.json')
const OUTPUT_FILE = path.resolve(CLI_ROOT, 'schema/command-mappings-enhanced.json')

// Load tool definitions and input schemas
const toolDefinitions = JSON.parse(fs.readFileSync(TOOL_DEFINITIONS_FILE, 'utf8'))
const toolInputs = JSON.parse(fs.readFileSync(TOOL_INPUTS_FILE, 'utf8'))

interface ToolDefinition {
  description: string
  category: string
  feature: string
  summary: string
  title: string
  required_scopes: string[]
}

interface ToolInfo {
  name: string
  humanName: string
  description: string
  category: string
  endpoint?: string
  method?: string
  inputs: any
  mcp_tool: string
}

// Resource groupings for CLI commands
const RESOURCE_GROUPS: Record<string, string[]> = {
  'insights': ['insight', 'insights'],
  'dashboards': ['dashboard', 'dashboards'],
  'events': ['event', 'events'],
  'actions': ['action', 'actions'],
  'cohorts': ['cohort', 'cohorts'],
  'persons': ['person', 'persons'],
  'feature-flags': ['feature-flag', 'feature-flags'],
  'experiments': ['experiment', 'experiments'],
  'surveys': ['survey', 'surveys'],
  'session-recordings': ['session-recording', 'session-recordings'],
  'batch-exports': ['batch-export', 'batch-exports'],
  'alerts': ['alert', 'alerts'],
  'error-tracking': ['error-tracking'],
  'llm-analytics': ['llma'],
  'annotations': ['annotation', 'annotations'],
  'organizations': ['org', 'organization', 'organizations'],
  'projects': ['project', 'projects'],
  'workflows': ['workflow', 'workflows'],
  'hog-functions': ['hog', 'cdp-function'],
  'early-access-features': ['early-access'],
  'logs': ['logs'],
  'notebooks': ['notebook', 'notebooks'],
  'integrations': ['integration', 'integrations'],
  'usage': ['usage'],
  'sql': ['sql'],
  'activity-logs': ['activity-log'],
  'feedback': ['agent-feedback', 'feedback'],
  'apm': ['apm'],
  'approvals': ['approval', 'change-request'],
  'properties': ['property', 'properties'],
  'data-warehouse': ['external-data', 'data-warehouse', 'warehouse'],
  'subscriptions': ['subscription', 'subscriptions'],
  'roles': ['role', 'roles'],
  'users': ['user', 'users'],
  'comments': ['comment', 'comments'],
  'support': ['conversations-tickets', 'support', 'ticket'],
  'debug': ['debug'],
  'docs': ['docs', 'documentation'],
  'endpoints': ['endpoint'],
  'web-analytics': ['web-analytics'],
}

function findResourceGroup(toolName: string): string | null {
  for (const [groupKey, patterns] of Object.entries(RESOURCE_GROUPS)) {
    for (const pattern of patterns) {
      if (toolName.includes(pattern)) {
        return groupKey
      }
    }
  }
  return null
}

function generateHumanReadableName(toolName: string, description: string, summary: string): string {
  const desc = (summary || description).toLowerCase()
  
  // Specific mappings for common patterns
  const specificMappings: Record<string, string> = {
    'add-person-to-cohort': 'add-persons',
    'remove-person-from-static-cohort': 'remove-persons',
    'feature-flags-status-retrieve': 'status',
    'feature-flags-evaluation-reasons-retrieve': 'evaluation-reasons',
    'feature-flags-user-blast-radius-create': 'blast-radius',
    'feature-flags-test-evaluation-create': 'test-evaluation',
    'experiment-results-retrieve': 'results',
    'experiment-results-get': 'results',
    'insights-all-activity-retrieve': 'recent-activity',
    'activity-log-list': 'list',
    'switch-organization': 'switch-organization',
    'switch-project': 'switch-project',
  }

  if (specificMappings[toolName]) {
    return specificMappings[toolName]
  }

  // Pattern-based generation
  if (desc.includes('list') || desc.includes('get all')) return 'list'
  if (desc.includes('create') || desc.includes('add new')) return 'create'
  if (desc.includes('update') && !desc.includes('add') && !desc.includes('remove')) return 'update'
  if (desc.includes('delete') || (desc.includes('remove') && !desc.includes('person'))) return 'delete'
  if (desc.includes('get') && !desc.includes('get all')) return 'get'
  if (desc.includes('status')) return 'status'
  if (desc.includes('results')) return 'results'
  if (desc.includes('activity')) return 'activity'
  if (desc.includes('duplicate')) return 'duplicate'
  if (desc.includes('copy')) return 'copy'
  if (desc.includes('launch') || desc.includes('start')) return 'launch'
  if (desc.includes('pause')) return 'pause'
  if (desc.includes('resume')) return 'resume'
  if (desc.includes('end') || desc.includes('stop')) return 'end'
  if (desc.includes('archive')) return 'archive'
  
  // Extract from tool name as fallback
  const parts = toolName.split('-')
  const actionParts = parts.filter(p => 
    ['create', 'get', 'list', 'update', 'delete', 'launch', 'pause', 'resume', 'end', 'archive'].includes(p)
  )
  
  return actionParts.length > 0 ? actionParts[0] : parts[parts.length - 1]
}

async function extractEndpointFromGeneratedTool(toolName: string): Promise<{ endpoint?: string, method?: string }> {
  // First, check if we have a specific mapping for this tool
  const specificMappings: Record<string, { endpoint: string, method: string }> = {
    'feature-flags-status-retrieve': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/',
      method: 'GET'
    },
    'feature-flags-evaluation-reasons-retrieve': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/evaluation_reasons/',
      method: 'GET'
    },
    'feature-flags-user-blast-radius-create': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/user_blast_radius/',
      method: 'POST'
    },
    'feature-flags-test-evaluation-create': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/test_evaluation/',
      method: 'POST'
    },
    // Fix common problematic mappings
    'create-feature-flag': {
      endpoint: '/api/projects/{project_id}/feature_flags/',
      method: 'POST'
    },
    'delete-feature-flag': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/',
      method: 'PATCH'  // PostHog uses PATCH with { deleted: true }
    },
    'feature-flag-get-all': {
      endpoint: '/api/projects/{project_id}/feature_flags/',
      method: 'GET'
    },
    'actions-get-all': {
      endpoint: '/api/projects/{project_id}/actions/',
      method: 'GET'
    },
    'query-logs': {
      endpoint: '/api/projects/{project_id}/logs/query/',
      method: 'POST'
    }
  }
  
  if (specificMappings[toolName]) {
    return specificMappings[toolName]
  }
  
  try {
    // Try to dynamically import and analyze the generated tool
    const toolPath = `${MCP_ROOT}/src/tools/generated`
    
    // Find which file contains this tool by checking common patterns
    const possibleFiles = [
      'feature_flags.ts', 'cohorts.ts', 'experiments.ts', 'dashboards.ts', 
      'insights.ts', 'actions.ts', 'persons.ts', 'surveys.ts', 'batch_exports.ts',
      'alerts.ts', 'error_tracking.ts', 'llm_analytics.ts', 'annotations.ts',
      'core.ts', 'platform_features.ts', 'product_analytics.ts', 'workflows.ts',
      'notebooks.ts', 'data_warehouse.ts', 'web_analytics.ts'
    ]
    
    for (const file of possibleFiles) {
      const filePath = path.join(toolPath, file)
      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, 'utf8')
        
        // Look for the tool name in the file and try to extract endpoint patterns
        if (content.includes(`'${toolName}'`)) {
          // Look for context.api.request call in the tool's section
          const toolSectionRegex = new RegExp(`name:\\s*['"]${toolName}['"]([\\s\\S]*?)(?=\\{\\s*name:|$)`, 's')
          const toolSectionMatch = content.match(toolSectionRegex)
          
          if (toolSectionMatch) {
            const toolSection = toolSectionMatch[1]
            const requestMatch = toolSection.match(/context\.api\.request\(\s*\{\s*([^}]+)\s*\}/)
            
            if (requestMatch) {
              const requestCode = requestMatch[1]
              const pathMatch = requestCode.match(/path:\s*`([^`]+)`/)
              const methodMatch = requestCode.match(/method:\s*['"]([^'"]+)['"]/)
              
              if (pathMatch && methodMatch) {
                let path = pathMatch[1]
              const method = methodMatch[1]
            
            // Clean up template strings to simple placeholders
            if (path) {
              path = path
                .replace(/\$\{encodeURIComponent\(String\(projectId\)\)\}/g, '{project_id}')
                .replace(/\$\{encodeURIComponent\(String\(orgId\)\)\}/g, '{org_id}')
                .replace(/\$\{encodeURIComponent\(String\(params\.id\)\)\}/g, '{id}')
                .replace(/\$\{encodeURIComponent\(String\(params\.[^}]+\)\)\}/g, (match) => {
                  // Handle other params like {params.something}
                  const paramName = match.match(/params\.(\w+)/)?.[1]
                  return paramName ? `{${paramName}}` : match
                })
                .replace(/\$\{encodeURIComponent\(String\([^}]+\)\)\}/g, (match) => {
                  // Handle any other variables like orgId, userId, etc.
                  const varName = match.match(/String\((\w+)\)/)?.[1]
                  if (varName) {
                    // Convert camelCase to snake_case
                    const snakeCaseName = varName.replace(/([A-Z])/g, '_$1').toLowerCase()
                    return `{${snakeCaseName}}`
                  }
                  return match
                })
            }
            
              return { endpoint: path, method: method }
            }
            }
          }
        }
      }
    }
  } catch (error) {
    // Ignore errors, we'll use fallback patterns
  }
  
  // Fallback: infer from tool name patterns
  return inferEndpointFromName(toolName)
}

function inferEndpointFromName(toolName: string): { endpoint?: string, method?: string } {
  // Specific mappings for known tools that don't follow the general pattern
  const specificMappings: Record<string, { endpoint: string, method: string }> = {
    'feature-flags-status-retrieve': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/',
      method: 'GET'
    },
    'feature-flags-evaluation-reasons-retrieve': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/evaluation_reasons/',
      method: 'GET'
    },
    'feature-flags-user-blast-radius-create': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/user_blast_radius/',
      method: 'POST'
    },
    'feature-flags-test-evaluation-create': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/test_evaluation/',
      method: 'POST'
    },
    // Fix common problematic mappings
    'create-feature-flag': {
      endpoint: '/api/projects/{project_id}/feature_flags/',
      method: 'POST'
    },
    'delete-feature-flag': {
      endpoint: '/api/projects/{project_id}/feature_flags/{id}/',
      method: 'PATCH'  // PostHog uses PATCH with { deleted: true }
    },
    'feature-flag-get-all': {
      endpoint: '/api/projects/{project_id}/feature_flags/',
      method: 'GET'
    },
    'actions-get-all': {
      endpoint: '/api/projects/{project_id}/actions/',
      method: 'GET'
    },
    'query-logs': {
      endpoint: '/api/projects/{project_id}/logs/query/',
      method: 'POST'
    }
  }

  if (specificMappings[toolName]) {
    return specificMappings[toolName]
  }

  const resourceMap: Record<string, string> = {
    'feature-flag': 'feature_flags',
    'feature-flags': 'feature_flags',
    'batch-export': 'batch_exports',
    'session-recording': 'session_recordings',
    'early-access': 'early_access_features',
    'hog': 'hog_functions',
    'error-tracking': 'error_tracking',
    'web-analytics': 'web_analytics',
    'activity-log': 'activity_log',
    'llma': 'llm_analytics',
    'cohorts': 'cohorts',
    'cohort': 'cohorts',
    'insights': 'insights', 
    'insight': 'insights',
    'dashboards': 'dashboards',
    'dashboard': 'dashboards',
    'actions': 'actions',
    'action': 'actions',
    'persons': 'persons',
    'person': 'persons',
    'events': 'events',
    'event': 'events'
  }

  let resource = 'unknown'
  let method = 'GET'
  
  // Find resource from tool name
  for (const [key, value] of Object.entries(resourceMap)) {
    if (toolName.includes(key)) {
      resource = value
      break
    }
  }
  
  if (resource === 'unknown') {
    const parts = toolName.split('-')
    const firstPart = parts[0]
    // Only pluralize if it doesn't already end in 's'
    resource = firstPart.endsWith('s') ? firstPart : firstPart + 's'
  }
  
  // Determine method from action
  if (toolName.includes('-create')) method = 'POST'
  else if (toolName.includes('-update') || toolName.includes('-partial-update')) method = 'PATCH'
  else if (toolName.includes('-delete') || toolName.includes('-destroy')) method = 'DELETE'
  else method = 'GET'
  
  // Build endpoint pattern
  let endpoint = `/api/projects/{project_id}/${resource}/`
  
  // Add ID parameter for single resource operations (but NOT for list/get-all operations)
  if ((toolName.includes('-get') || toolName.includes('-update') || toolName.includes('-delete') || 
      toolName.includes('-retrieve') || toolName.includes('-destroy') || toolName.includes('-status')) &&
      !toolName.includes('-get-all') && !toolName.includes('-list')) {
    endpoint += '{id}/'
  }
  
  return { endpoint, method }
}

async function generateEnhancedMapping(): Promise<void> {
  console.log('🔧 Extracting tool information from generated MCP tools...')
  
  const commands: Record<string, {
    description: string
    subcommands: Record<string, ToolInfo>
  }> = {}
  
  let processedCount = 0
  
  // Process each tool definition
  for (const [toolName, tool] of Object.entries(toolDefinitions)) {
    const typedTool = tool as ToolDefinition
    const resourceGroup = findResourceGroup(toolName)
    
    if (!resourceGroup) {
      console.log(`⚠️  No resource group found for: ${toolName}`)
      continue
    }
    
    // Initialize command group if not exists
    if (!commands[resourceGroup]) {
      commands[resourceGroup] = {
        description: `Manage ${resourceGroup}`,
        subcommands: {}
      }
    }
    
    // Generate human-readable name
    const humanName = generateHumanReadableName(toolName, typedTool.description, typedTool.summary)
    
    // Extract endpoint information
    const { endpoint, method } = await extractEndpointFromGeneratedTool(toolName)
    
    // Get input schema if available
    const inputSchema = toolInputs.definitions?.[`${toolName.charAt(0).toUpperCase()}${toolName.slice(1).replace(/-([a-z])/g, (_, char) => char.toUpperCase())}Schema`]
    
    // Handle duplicate names
    let finalName = humanName
    let suffix = 1
    while (commands[resourceGroup].subcommands[finalName]) {
      finalName = `${humanName}-${suffix}`
      suffix++
    }
    
    commands[resourceGroup].subcommands[finalName] = {
      name: finalName,
      humanName: finalName,
      description: typedTool.summary || typedTool.description.split('.')[0] || typedTool.title,
      category: typedTool.category,
      endpoint,
      method,
      inputs: inputSchema || {},
      mcp_tool: toolName
    }
    
    processedCount++
  }
  
  // Create the enhanced mapping structure
  const enhancedMapping = {
    version: '2.0',
    generated_at: new Date().toISOString(),
    commands,
    stats: {
      total_tools: Object.keys(toolDefinitions).length,
      mapped_tools: processedCount,
      commands_created: Object.keys(commands).length
    }
  }
  
  // Write the enhanced mapping
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(enhancedMapping, null, 2))
  
  console.log(`✅ Generated enhanced command mappings`)
  console.log(`📊 Processed: ${processedCount}/${Object.keys(toolDefinitions).length} tools`)
  console.log(`🏗️  Created: ${Object.keys(commands).length} command groups`)
  console.log(`📄 Output: ${OUTPUT_FILE}`)
}

async function main() {
  try {
    await generateEnhancedMapping()
    console.log('🎉 Enhanced mapping generation complete!')
  } catch (error) {
    console.error('❌ Failed to generate enhanced mappings:', error)
    process.exit(1)
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main()
}