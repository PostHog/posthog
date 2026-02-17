// W3C WebMCP types for navigator.modelContext
// See: https://webmachinelearning.github.io/webmcp/

export interface WebMcpToolContent {
    type: 'text' | 'json'
    text?: string
    json?: Record<string, unknown>
}

export interface WebMcpToolResult {
    content: WebMcpToolContent[]
    isError?: boolean
}

export interface WebMcpToolRegistration {
    unregister(): void
}

export interface WebMcpToolAnnotations {
    readOnly?: boolean
}

export interface WebMcpTool {
    name: string
    description: string
    inputSchema: Record<string, unknown>
    execute: (args: Record<string, unknown>) => Promise<WebMcpToolResult>
    annotations?: WebMcpToolAnnotations
}

export interface ModelContext {
    registerTool(tool: WebMcpTool): WebMcpToolRegistration
}

declare global {
    interface Navigator {
        modelContext?: ModelContext
    }
}
