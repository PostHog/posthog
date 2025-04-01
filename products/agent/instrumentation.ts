import { GoogleGenerativeAI } from '@google/generative-ai'
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
  importPattern: string
  capturePattern: RegExp
  propertiesExtractor: (match: RegExpExecArray) => Record<string, any> | undefined
  descriptionFromContext: () => string
}

interface DocsConfig {
  pattern: string
  productDescription: string
  analyticsDoc: string
  parsing: EventParsingConfig
}

interface ProductConfig {
  title: string
  description: string
  files: string[]
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

// Configuration for different file types
const DOCS_BY_TYPE: DocsConfig[] = [
  {
    pattern: '**/*.tsx',
    productDescription: 'React/TypeScript frontend code that handles user interactions and UI components.',
    analyticsDoc: `
Setup:
import posthog from 'posthog-js'

Example events to track:

1. User Interactions
   posthog.capture('signup_button_clicked', {
      button_name: 'name',
      location: 'component'
    })

2. Error States
   posthog.capture('upload_file_error')`,
    parsing: {
      importPattern: "import posthog from 'posthog-js'",
      capturePattern: /posthog\.capture\(['"]([^'"]+)['"](?:,\s*({[^}]+}))?\)/g,
      propertiesExtractor: (match) => {
        if (!match[2]) { return undefined }
        try {
          const cleaned = match[2]
            .replace(/(\w+):/g, '"$1":')
            .replace(/'/g, '"')
            .replace(/,\s*}/g, '}')
          return JSON.parse(cleaned)
        } catch (e) {
          return undefined
        }
      },
      descriptionFromContext: () => 'Event'
    }
  },
  {
    pattern: '**/*.py',
    productDescription: 'Python backend code that handles business logic and API endpoints.',
    analyticsDoc: `
Setup:
from posthog import Posthog
posthog = Posthog(project_api_key='<ph_project_api_key>')

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
      importPattern: 'from posthog import Posthog',
      capturePattern: /posthog\.capture\(\s*(?:distinct_id=['"]\w+['"],\s*)?event=['"]([^'"]+)['"](?:,\s*properties=({[^}]+}))?\)/g,
      propertiesExtractor: (match) => {
        if (!match[2]) { return undefined }
        try {
          const cleaned = match[2]
            .replace(/'/g, '"')
            .replace(/True/g, 'true')
            .replace(/False/g, 'false')
            .replace(/None/g, 'null')
          return JSON.parse(cleaned)
        } catch (e) {
          return undefined
        }
      },
      descriptionFromContext: () => 'Event'
    }
  }
]

const ANALYTICS_BASE_PROMPT = `You are an analytics implementation expert. Your goal is to analyze code and add appropriate posthog.capture() calls to track key user interactions and important events.

Analyze the code and determine what events would be valuable to track based on:
1. The product's purpose and functionality
2. User interactions and flows
3. Important state changes and operations
4. Error cases and edge conditions

Guidelines:
- Event names should be snake_case
- Include relevant properties that provide context
- Don't track sensitive information
- Don't duplicate existing capture calls
- Place capture calls in appropriate locations (handlers, effects, etc.)
- Return ONLY the exact code that should be written to the file. Do not include any markdown formatting, code block markers, or explanation. The output should be exactly what will be written to the file, nothing more and nothing less.
- Make minimal changes to the code, avoid adding new code focus on simple modifications to existing code to add analytics events.`

const genAI = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY)
const model = genAI.getGenerativeModel({
  model: 'gemini-2.0-flash',
  generationConfig: {
    temperature: 0.2,
  }
})

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
${filePath}

Current file content:
${content}`

  const { response } = await model.generateContent({
    contents: [
      { role: 'model', parts: [{ text: systemPrompt }] },
      { role: 'user', parts: [{ text: userPrompt }] }
    ],
  })

  const modifiedContent = response.text().replace(/^(```[^\n]*\n|```)|```$/g, '')
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
      ignore: ['**/node_modules/**', '**/dist/**', '**/build/**', '**/*.test.*', '**/*.spec.*', '**/__tests__/**'],
      absolute: true
    })
    return matches.some(match => path.resolve(match) === path.resolve(filePath))
  })
}

async function main(): Promise<void> {
  const targetPaths = PRODUCT_CONFIG.files
  const skippedFiles: string[] = []
  let modifiedCount = 0

  for (const targetPath of targetPaths) {
    let filePaths: string[]

    if (fsSync.statSync(targetPath).isDirectory()) {
      filePaths = fg.sync('**/*.{tsx,jsx,ts,js,py}', {
        cwd: targetPath,
        ignore: [
          '**/node_modules/**',
          '**/dist/**',
          '**/build/**',
          '**/*.test.*',
          '**/*.spec.*',
          '**/__tests__/**',
          '**/*.d.ts'
        ],
        absolute: true
      })
    } else {
      filePaths = [targetPath]
    }

    for (const filePath of filePaths) {
      const config = findMatchingConfig(filePath)

      if (!config) {
        skippedFiles.push(filePath)
        continue
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
        skippedFiles.push(filePath)
      }
    }
  }

  // Print final summary
  console.log('\nSummary:')
  console.log(`Modified ${modifiedCount} files`)
  console.log(`Skipped ${skippedFiles.length} files`)

  if (skippedFiles.length > 0) {
    console.log('\nSkipped files (no matching config or error):')
    skippedFiles.forEach(file => console.log(`- ${file}`))
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error('Fatal error:', error)
    process.exit(1)
  })
} 