import Anthropic from '@anthropic-ai/sdk'
import { mapLimit } from 'async'
import * as fg from 'fast-glob'
import * as fsSync from 'fs'
import * as fs from 'fs/promises'
import * as path from 'path'

interface AnalyticsEvent {
  event: string
  location: {
    file: string
    lineNumber: number
  }
}

interface FileModification {
  filePath: string
  originalContent: string
  modifiedContent: string
  addedEvents: AnalyticsEvent[]
}

interface EventParsingConfig {
  capturePattern: RegExp
}

interface DocsConfig {
  pattern: string
  analyticsDoc: string
  parsing: EventParsingConfig
}

interface ProductConfig {
  title: string
  description: string
  files: string[]
}

interface AgentOptions {
  concurrency: number
  costs: {
    inputTokenRate: number  // USD per million tokens
    outputTokenRate: number // USD per million tokens
  }
  ignore: string[]
  model: string
}

const PRODUCT_CONFIG: ProductConfig = {
  title: 'LLM Observability',
  description: `PostHog's LLM Observability product helps teams monitor, debug, and improve their LLM applications.
Key features:
- Trace visualization of LLM interactions
- Performance and cost monitoring
- User feedback tracking
- Error and edge case detection
- Model comparison and evaluation`,
  files: [
    'products/llm_observability/frontend/LLMObservabilityScene.tsx',
    'products/llm_observability/frontend/LLMObservabilityTraceScene.tsx',
    'products/llm_observability/frontend/LLMObservabilityTracesScene.tsx',
    'products/llm_observability/frontend/LLMObservabilityUsers.tsx',
    'products/llm_observability/frontend/llmObservabilityLogic.tsx',
    'products/llm_observability/frontend/llmObservabilityTraceDataLogic.ts',
    'products/llm_observability/frontend/llmObservabilityTraceLogic.ts',
    'products/llm_observability/frontend/utils.ts',
    'products/llm_observability/frontend/components/FeedbackTag.tsx',
    'products/llm_observability/frontend/components/MetadataTag.tsx',
    'products/llm_observability/frontend/components/MetricTag.tsx'
  ]
}

const AGENT_OPTIONS: AgentOptions = {
  concurrency: 5,
  costs: {
    inputTokenRate: 3,   // $3 per million tokens for Claude 3.7
    outputTokenRate: 15   // $15 per million tokens for Claude 3.7
  },
  ignore: [
    '**/node_modules/**',
    '**/dist/**',
    '**/build/**',
    '**/*.test.*',
    '**/*.spec.*',
    '**/__tests__/**',
    '**/*.d.ts'
  ],
  model: 'claude-3-7-sonnet-20250219'
}

// Configuration for different file types
const DOCS_BY_TYPE: DocsConfig[] = [
  {
    pattern: '**/*.{tsx,jsx}',
    analyticsDoc: `
Setup:
import posthog from 'posthog-js'

Integration Specific Rules:
- Focus on click handlers and other props you know will exist - do not add props that are not known to exist for a component (e.g. a custom component might not have a click handler).
- Make sure events are as a result of user interaction e.g. a button click or a form submission and not something that happens as a result of a component mounting / rendering which could cause a lot of noise.
- Do not add properties to a custom component that are not known to exist

Example events to track:

1. User Interactions
   posthog.capture('signup_button_clicked', {
      button_name: 'name',
      location: 'component'
    })

2. Error States
   posthog.capture('upload_file_error')`,
    parsing: {
      capturePattern: /posthog\.capture\(['"]([^'"]+)['"](?:,\s*({[^}]+}))?\)/g,
    }
  },
  {
    pattern: '**/*.py',
    analyticsDoc: `
Setup:
from posthog import Posthog
posthog = Posthog(project_api_key='<ph_project_api_key>')

Integration Specific Rules:
- 

Example events to track:

1. Feature Usage
   posthog.capture(
       distinct_id='user_id',
       event='export_report_requested',
       properties={
           'report_type': 'performance',
           'date_range': '7d'
       }
   )

2. Error States
   posthog.capture(
       distinct_id='user_id',
       event='model_inference_failed'
   )`,
    parsing: {
      capturePattern: /posthog\.capture\(\s*(?:distinct_id=['"]\w+['"],\s*)?event=['"]([^'"]+)['"](?:,\s*properties=({[^}]+}))?\)/g,
    }
  }
]

const ANALYTICS_BASE_PROMPT = `You are an analytics implementation expert. Your goal is to analyze code and add appropriate posthog.capture() calls to track key user interactions and important events.

Analyze the code and determine what events would be valuable to track based on:
1. The product's purpose and functionality
2. User interactions and flows
3. Important state changes and operations
4. Error cases and edge conditions

General Rules:
- Event names should be snake_case
- Include relevant properties that provide context
- Don't track sensitive information
- Don't duplicate existing capture calls
- Place capture calls in appropriate locations (handlers, effects, etc.)
- Return ONLY the exact code that should be written to the file. Do not include any markdown formatting, code block markers, or explanation. The output should be exactly what will be written to the file, nothing more and nothing less.
- Make minimal changes to the code, avoid adding new code focus on simple modifications to existing code to add analytics events.
- You should avoid breaking the code, so if you are unsure whether a change will break the code, ask the user for clarification.
- You should avoid adding analytics events that will break the code, so if you are unsure whether an event will break the code, just skip it.
- Make sure events are not duplicated, if an event is already being tracked, do not add another one.`

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY
})

let inputTokens = 0
let outputTokens = 0

async function analyzeFile(
  filePath: string,
  analyticsDoc: string
): Promise<FileModification> {
  const content = await fs.readFile(filePath, 'utf8')

  const systemPrompt = `${ANALYTICS_BASE_PROMPT}

Product: ${PRODUCT_CONFIG.title}
Description: ${PRODUCT_CONFIG.description}

Analytics Setup and Examples:
${analyticsDoc}`

  const userPrompt = `Analyze and add analytics events to this file:

Current file path: ${filePath}
Current file content:
${content}`

  const message = await anthropic.messages.create({
    model: AGENT_OPTIONS.model,
    system: systemPrompt,
    messages: [
      { role: 'user', content: userPrompt }
    ],
    max_tokens: 4096,
    temperature: 0.1
  })

  inputTokens += message.usage?.input_tokens || 0
  outputTokens += message.usage?.output_tokens || 0

  // Get the text content, handling potential text/image content blocks
  const modifiedContent = message.content.find(block => block.type === 'text')?.text || ''
  const addedEvents = extractAddedEvents(content, modifiedContent, filePath)

  return {
    filePath,
    originalContent: content,
    modifiedContent,
    addedEvents
  }
}

function extractAddedEvents(
  original: string,
  modified: string,
  filePath: string
): AnalyticsEvent[] {
  const events: AnalyticsEvent[] = []
  const capturePattern = /posthog\.capture\(['"]([^'"]+)['"](?:,\s*(?:{[^}]+}))?\)/g

  let match
  while ((match = capturePattern.exec(modified)) !== null) {
    if (!original.includes(match[0])) {
      const lineNumber = modified.substring(0, match.index).split('\n').length

      events.push({
        event: match[1],
        location: {
          file: filePath,
          lineNumber
        }
      })
    }
  }

  return events
}

async function writeModification(modification: FileModification): Promise<void> {
  await fs.writeFile(modification.filePath, modification.modifiedContent)
  console.log(`Modified ${modification.filePath}`)
  console.log('Added events:', modification.addedEvents)
}

function findMatchingConfig(filePath: string): DocsConfig | undefined {
  return DOCS_BY_TYPE.find(config => {
    const matches = fg.sync(config.pattern, {
      ignore: AGENT_OPTIONS.ignore,
      absolute: true
    })
    return matches.some(match => path.resolve(match) === path.resolve(filePath))
  })
}

async function main(): Promise<void> {
  const targetPaths = PRODUCT_CONFIG.files
  let modifiedCount = 0
  let skippedCount = 0

  // Collect all file paths to process
  const allFilePaths: string[] = []
  for (const targetPath of targetPaths) {
    if (fsSync.statSync(targetPath).isDirectory()) {
      const files = fg.sync('**/*.{tsx,jsx,ts,js,py}', {
        cwd: targetPath,
        ignore: AGENT_OPTIONS.ignore,
        absolute: true
      })
      allFilePaths.push(...files)
    } else {
      allFilePaths.push(targetPath)
    }
  }

  // Process files in parallel
  await mapLimit(allFilePaths, AGENT_OPTIONS.concurrency, async (filePath: string) => {
    const config = findMatchingConfig(filePath)
    if (!config) {
      skippedCount++
      return
    }

    try {
      console.log(`Processing ${filePath}...`)
      const modification = await analyzeFile(
        filePath,
        config.analyticsDoc
      )

      await writeModification(modification)
      modifiedCount++
    } catch (error) {
      console.error(`Error processing ${filePath}:`, error)
      skippedCount++
    }
  })

  const inputCost = (inputTokens * AGENT_OPTIONS.costs.inputTokenRate) / 1000000
  const outputCost = (outputTokens * AGENT_OPTIONS.costs.outputTokenRate) / 1000000
  const totalCost = inputCost + outputCost

  // Print final summary
  console.log('\nSummary:')
  console.log(`Modified ${modifiedCount} files`)
  console.log(`Skipped ${skippedCount} files`)

  // Print cost estimates
  console.log('\nCost Estimates:')
  console.log(`Input tokens: ${inputTokens}`)
  console.log(`Input cost: $${inputCost.toFixed(6)} USD`)
  console.log(`Output tokens: ${outputTokens}`)
  console.log(`Output cost: $${outputCost.toFixed(6)} USD`)
  console.log(`Total cost: $${totalCost.toFixed(6)} USD`)
}

if (require.main === module) {
  main().catch(error => {
    console.error('Fatal error:', error)
    process.exit(1)
  })
} 