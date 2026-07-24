import { ReactNode, useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

interface MCPEventViewProps {
    properties: Record<string, any>
}

interface MCPEntry {
    key: string
    value: unknown
    bytes: number
}

// Values whose serialized payload exceeds this get a per-row "Show N B" disclosure
// so a single fat field (parameters, response, tool descriptions, etc.) can't take
// over the whole property list.
const LONG_VALUE_BYTES = 256
// Bounded scroll for expanded values; viewport-relative so it adapts to drawer size
// instead of a fixed pixel cap.
const EXPANDED_MAX_HEIGHT = '50dvh'

const measureBytes = (value: unknown): number => {
    const text = typeof value === 'string' ? value : JSON.stringify(value ?? '')
    return new Blob([text]).size
}

const formatBytes = (bytes: number): string => {
    if (bytes < 1024) {
        return `${bytes} B`
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`
    }
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const makePreview = (value: unknown, maxChars = 80): string => {
    let text: string
    if (value === null || value === undefined) {
        text = String(value)
    } else if (typeof value === 'string') {
        text = value.replace(/\s+/g, ' ').trim()
    } else if (Array.isArray(value)) {
        text = `[${value.length} item${value.length === 1 ? '' : 's'}]`
    } else if (typeof value === 'object') {
        const keys = Object.keys(value as object)
        text = `{ ${keys.slice(0, 3).join(', ')}${keys.length > 3 ? ', …' : ''} }`
    } else {
        text = String(value)
    }
    return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text
}

// Display order for known MCP properties — groups semantically related rows.
// Unknown keys fall to the end, sorted alphabetically.
const MCP_PROPERTY_ORDER: readonly string[] = [
    // Payload
    '$mcp_parameters',
    '$mcp_response',
    // Outcome
    '$mcp_is_error',
    '$mcp_duration_ms',
    '$mcp_intent',
    '$mcp_intent_source',
    // What was called
    '$mcp_tool_name',
    '$mcp_tool_description',
    '$mcp_exec_inner_tool_name',
    '$mcp_exec_inner_tool_description',
    '$mcp_resource_name',
    // Session context
    '$mcp_session_id',
    '$mcp_conversation_id',
    '$mcp_mode',
    '$mcp_source',
    '$mcp_transport',
    // Client
    '$mcp_client_name',
    '$mcp_client_version',
    '$mcp_client_user_agent',
    // Server
    '$mcp_server_name',
    '$mcp_server_version',
    '$mcp_protocol_version',
    '$mcp_version',
    // PostHog target
    '$mcp_organization_id',
    '$mcp_project_id',
    '$mcp_project_name',
    '$mcp_project_uuid',
    '$mcp_region',
]

const orderIndex = (key: string): number => {
    // Accept both `$mcp_*` and the older un-prefixed `mcp_*` form.
    const normalized = key.startsWith('$') ? key : `$${key}`
    const idx = MCP_PROPERTY_ORDER.indexOf(normalized)
    return idx === -1 ? Number.MAX_SAFE_INTEGER : idx
}

function ValueCell({ value, bytes }: { value: unknown; bytes: number }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const valueType = value === null ? 'null' : typeof value
    const isLong = bytes > LONG_VALUE_BYTES

    const fullSerialized = typeof value === 'string' ? value : JSON.stringify(value ?? '')

    const typeTag = (
        <LemonTag className="font-mono uppercase" type="muted">
            {valueType}
        </LemonTag>
    )
    const copyButton = (
        <CopyToClipboardInline
            description="property value"
            explicitValue={fullSerialized}
            iconSize="xsmall"
            selectable
        />
    )

    if (!isLong) {
        const display =
            value === null || value === undefined
                ? String(value)
                : typeof value === 'object'
                  ? JSON.stringify(value)
                  : String(value)
        return (
            <div className="flex flex-row flex-wrap items-center gap-2 break-all">
                <span>{display}</span>
                {typeTag}
            </div>
        )
    }

    let expandedContent: JSX.Element
    let parsed: unknown = value
    if (typeof value === 'string') {
        try {
            parsed = JSON.parse(value)
        } catch {
            parsed = value
        }
    }
    if (parsed !== null && typeof parsed === 'object') {
        expandedContent = (
            <JSONViewer src={parsed as object} name={null} collapsed={1} collapseStringsAfterLength={120} sortKeys />
        )
    } else {
        expandedContent = (
            <pre className="m-0 whitespace-pre-wrap break-words text-xs leading-relaxed">{String(value)}</pre>
        )
    }

    return (
        <div className="flex w-full flex-col gap-1">
            <div className="flex w-full min-w-0 flex-row flex-nowrap items-center gap-2">
                <span className="text-secondary min-w-0 flex-1 truncate text-xs">{makePreview(value)}</span>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => setExpanded((e) => !e)}
                    aria-label={expanded ? 'Hide value' : `Show value (${formatBytes(bytes)})`}
                    className="shrink-0"
                >
                    {expanded ? 'Hide' : `Show ${formatBytes(bytes)}`}
                </LemonButton>
                <span className="shrink-0">{typeTag}</span>
                <span className="shrink-0">{copyButton}</span>
            </div>
            {expanded ? (
                <div
                    className="border-border mt-1 overflow-auto rounded border p-2"
                    style={{ maxHeight: EXPANDED_MAX_HEIGHT }}
                >
                    {expandedContent}
                </div>
            ) : null}
        </div>
    )
}

function Stat({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-1">
            <span className="text-secondary text-xs font-medium uppercase tracking-wide">{label}</span>
            <div className="text-sm">{children}</div>
        </div>
    )
}

export function MCPEventView({ properties }: MCPEventViewProps): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')

    const mcpProps = useMemo(
        () =>
            Object.fromEntries(
                Object.entries(properties).filter(([k]) => k.startsWith('$mcp_') || k.startsWith('mcp_'))
            ),
        [properties]
    )

    let displayName: string | undefined
    let displayKind: string | undefined
    if (mcpProps['$mcp_tool_name'] !== undefined) {
        displayName = String(mcpProps['$mcp_tool_name'])
        displayKind = 'Tool'
    } else if (mcpProps['$mcp_resource_name'] !== undefined) {
        displayName = String(mcpProps['$mcp_resource_name'])
        displayKind = 'Resource'
    }
    const rawIsError = mcpProps['$mcp_is_error']
    // Normalise — ingestion can flatten booleans to strings, and "false" is truthy in JS.
    const hasErrorStatus = rawIsError !== undefined && rawIsError !== null
    const isError = rawIsError === true || rawIsError === 'true'
    const durationMs = mcpProps['$mcp_duration_ms']
    const clientName = mcpProps['$mcp_client_name']
    const serverName = mcpProps['$mcp_server_name']
    const intent = mcpProps['$mcp_intent']
    const intentSource = mcpProps['$mcp_intent_source']
    const hasSummaryStat =
        hasErrorStatus ||
        Boolean(displayName && displayKind) ||
        (durationMs !== undefined && durationMs !== null) ||
        Boolean(clientName) ||
        Boolean(serverName) ||
        Boolean(intent)

    const entries: MCPEntry[] = useMemo(() => {
        const arr = Object.entries(mcpProps).map(([key, value]) => ({
            key,
            value,
            bytes: measureBytes(value),
        }))
        arr.sort((a, b) => orderIndex(a.key) - orderIndex(b.key) || a.key.localeCompare(b.key))
        return arr
    }, [mcpProps])

    const filteredEntries: MCPEntry[] = useMemo(() => {
        if (!searchTerm) {
            return entries
        }
        const needle = searchTerm.toLowerCase()
        return entries.filter(({ key, value }) => {
            if (key.toLowerCase().includes(needle)) {
                return true
            }
            const serialized = typeof value === 'string' ? value : JSON.stringify(value ?? '')
            return serialized.toLowerCase().includes(needle)
        })
    }, [entries, searchTerm])

    const columns: LemonTableColumns<MCPEntry> = [
        {
            key: 'key',
            title: 'Key',
            render: (_, item) => (
                <div className="properties-table-key">
                    <PropertyKeyInfo value={item.key} type={TaxonomicFilterGroupType.EventProperties} />
                </div>
            ),
        },
        {
            key: 'value',
            title: 'Value',
            fullWidth: true,
            render: (_, item) => <ValueCell value={item.value} bytes={item.bytes} />,
        },
    ]

    return (
        <div className="mx-3 flex flex-col gap-3">
            {hasSummaryStat ? (
                <div className="border-border bg-surface-secondary flex flex-wrap items-start gap-x-6 gap-y-3 rounded border p-3">
                    {hasErrorStatus ? (
                        <Stat label="Status">
                            <LemonTag type={isError ? 'danger' : 'success'}>{isError ? 'Error' : 'Success'}</LemonTag>
                        </Stat>
                    ) : null}
                    {displayName && displayKind ? (
                        <Stat label={displayKind}>
                            <span className="font-semibold">{displayName}</span>
                        </Stat>
                    ) : null}
                    {durationMs !== undefined && durationMs !== null ? (
                        <Stat label="Duration">{String(durationMs)} ms</Stat>
                    ) : null}
                    {clientName ? <Stat label="Client">{String(clientName)}</Stat> : null}
                    {serverName ? <Stat label="Server">{String(serverName)}</Stat> : null}
                    {intent ? (
                        <div className="basis-full">
                            <Stat
                                label={intentSource ? `Intent (${String(intentSource).replace(/_/g, ' ')})` : 'Intent'}
                            >
                                <Tooltip title={String(intent)}>
                                    <span className="block whitespace-pre-wrap break-words">{String(intent)}</span>
                                </Tooltip>
                            </Stat>
                        </div>
                    ) : null}
                </div>
            ) : null}
            {entries.length > 6 ? (
                <LemonInput
                    type="search"
                    placeholder="Search property keys and values"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="w-64 max-w-full"
                />
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={filteredEntries}
                rowKey="key"
                embedded
                size="small"
                emptyState="No MCP properties match this search."
            />
        </div>
    )
}
