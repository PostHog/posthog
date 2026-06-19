/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface MemoryFileSummaryApi {
    /** Relative path of the file within the team's memory tree. */
    path: string
    /** Monotonic version of the file. */
    version: number
    /** UTF-8 byte length of the file's content. */
    size_bytes: number
    /**
     * Identifier of the agent run that last wrote the file, or null.
     * @nullable
     */
    updated_by_run: string | null
    updated_at: string
}

export interface PaginatedMemoryFileSummaryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MemoryFileSummaryApi[]
}

export interface MemoryAppendInputApi {
    /**
     * Relative path of the file to append to, e.g. 'project.md'. Created if it does not exist.
     * @maxLength 1024
     */
    path: string
    /**
     * Section title (without leading '#'). If a section with this title already exists, its body is replaced; otherwise a new '## {heading}' section is appended.
     * @maxLength 500
     */
    heading: string
    /**
     * Markdown body for the section. Never clobbers other sections of the file.
     * @maxLength 1000000
     */
    body: string
}

export interface MemoryFileApi {
    /** Relative path of the file within the team's memory tree, e.g. 'project.md'. */
    path: string
    /** Full markdown body of the file. */
    content: string
    /** Monotonic version of the file. Pass this back as `expected_version` on the next write to detect conflicting concurrent edits (compare-and-set). */
    version: number
    /**
     * ID of the user who last wrote the file, or null if written by an agent run.
     * @nullable
     */
    updated_by_id: number | null
    /**
     * Identifier of the agent run that last wrote the file, or null.
     * @nullable
     */
    updated_by_run: string | null
    created_at: string
    updated_at: string
}

export interface MemoryDeleteResponseApi {
    /** Whether a file was deleted. False means there was nothing to delete. */
    deleted: boolean
}

export interface MemoryWriteInputApi {
    /**
     * Relative path of the file to write, e.g. 'project.md' or 'users/jane-doe.md'. Must end in '.md', may not contain '..' or absolute segments.
     * @maxLength 1024
     */
    path: string
    /**
     * Full markdown body to store. Replaces the file's content entirely — prefer the append endpoint to add a section without clobbering concurrent edits.
     * @maxLength 1000000
     */
    content: string
    /**
     * Compare-and-set token. Omit (or null) to create a new file; pass the version you last read to update an existing one. A mismatch returns 409 — re-read and merge before retrying.
     * @nullable
     */
    expected_version?: number | null
}

export interface MemoryConflictResponseApi {
    /** Human-readable conflict description. */
    detail: string
    /** Stable error code; 'version_conflict' for compare-and-set failures. */
    code: string
    /** The path that conflicted. */
    path: string
    /** The version the writer supplied. */
    expected_version: number
    /** The version currently stored — re-read at this version. */
    actual_version: number
}

export type AgentMemoryListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return files whose path starts with this fragment, e.g. 'scouts/' or 'users/'.
     */
    prefix?: string
}

export type AgentMemoryFileDestroyParams = {
    /**
     * Relative path of the file to delete.
     */
    path: string
}

export type AgentMemoryReadRetrieveParams = {
    /**
     * Relative path of the file to read, e.g. 'project.md'.
     */
    path: string
}
