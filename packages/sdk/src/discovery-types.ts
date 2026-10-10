export interface ToolTypeReference {
    name: string
    /** npm subpath from which this type can be imported. */
    importPath: string
    /** File paths are relative to the installed package root. */
    source: string
    declaration: string
}

export interface DocumentationSource {
    kind: 'openapi' | 'query_schema' | 'mcp_yaml' | 'mcp_json' | 'mcp_typescript' | 'description_file' | 'adapter'
    file: string
    pointer?: string
}

export interface DocumentationLayer {
    role: 'original' | 'override' | 'generated'
    text: string
    source: DocumentationSource
}

export interface TypeDocumentation {
    typeName: string
    field?: string
    effectiveDescription: string
    layers: DocumentationLayer[]
}

export interface ToolAnnotations {
    readOnly: boolean
    destructive: boolean
    idempotent: boolean
}

export interface RelatedTool {
    toolName: string
    method?: string
    unavailableReason?: string
}

export interface ToolSearchResult {
    method: string
    toolName: string
    title: string
    selectionHint?: string
    descriptionFile: string
}

export interface ToolSearchOptions {
    /** Maximum results, between 1 and 100. Defaults to 10. */
    limit?: number
}

export interface ToolDescription {
    method: string
    toolName: string
    operationId?: string
    title: string
    category: string
    description: string
    selectionHint?: string
    requiredScopes: string[]
    annotations: ToolAnnotations
    availability: string[]
    methodSource: string
    input: ToolTypeReference
    output: ToolTypeReference
    referencedTypes: ToolTypeReference[]
    methodDocumentation: DocumentationLayer[]
    typeDocumentation: TypeDocumentation[]
    relatedTools: RelatedTool[]
}

export interface ToolCatalog {
    schemaVersion: number
    packageVersion: string
    /** Content hash of the generation inputs; it is independent of the checkout's changing HEAD. */
    sourceRevision: string
    schemaHash: string
    tools: ToolSearchResult[]
}
