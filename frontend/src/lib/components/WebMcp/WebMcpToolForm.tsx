import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { McpToolDefinition } from '~/types'

import { webMcpLogic } from './webMcpLogic'

interface WebMcpToolFormProps {
    /** Tool name to render the form for */
    toolName: string
    /** Optional callback when invocation completes */
    onResult?: (result: { success: boolean; content: string }) => void
}

interface JsonSchemaProperty {
    type?: string
    description?: string
    default?: any
    enum?: string[]
}

function FieldInput({
    name,
    property,
    value,
    onChange,
}: {
    name: string
    property: JsonSchemaProperty
    value: any
    onChange: (value: any) => void
}): JSX.Element {
    const fieldType = property.type ?? 'string'

    if (fieldType === 'boolean') {
        return (
            <LemonButton type={value ? 'primary' : 'secondary'} size="small" onClick={() => onChange(!value)}>
                {value ? 'true' : 'false'}
            </LemonButton>
        )
    }

    if (fieldType === 'integer' || fieldType === 'number') {
        return (
            <LemonInput
                type="number"
                value={value ?? ''}
                onChange={(val) => onChange(val == null ? undefined : Number(val))}
                placeholder={property.description ?? name}
                fullWidth
            />
        )
    }

    // For long text or objects/arrays, use textarea
    if (fieldType === 'object' || fieldType === 'array') {
        return (
            <LemonTextArea
                value={typeof value === 'string' ? value : JSON.stringify(value ?? '', null, 2)}
                onChange={(val) => {
                    try {
                        onChange(JSON.parse(val))
                    } catch {
                        onChange(val)
                    }
                }}
                placeholder={property.description ?? `JSON ${fieldType}`}
                minRows={3}
            />
        )
    }

    // Default: string input
    return <LemonInput value={value ?? ''} onChange={onChange} placeholder={property.description ?? name} fullWidth />
}

function buildInitialValues(tool: McpToolDefinition): Record<string, any> {
    const properties = (tool.input_schema?.properties ?? {}) as Record<string, JsonSchemaProperty>
    const values: Record<string, any> = {}
    for (const [key, prop] of Object.entries(properties)) {
        if (prop.default !== undefined) {
            values[key] = prop.default
        }
    }
    return values
}

export function WebMcpToolForm({ toolName, onResult }: WebMcpToolFormProps): JSX.Element {
    const logic = webMcpLogic({ key: 'global' })
    const { toolsByName, toolResults, activeInvocations } = useValues(logic)
    const { invokeTool, clearToolResult } = useActions(logic)

    const tool = toolsByName[toolName]
    const result = toolResults[toolName]
    const isLoading = !!activeInvocations[toolName]

    const [formValues, setFormValues] = useState<Record<string, any>>({})

    useEffect(() => {
        if (tool) {
            setFormValues(buildInitialValues(tool))
        }
    }, [tool])

    useEffect(() => {
        if (result && onResult) {
            onResult(result)
        }
    }, [result]) // eslint-disable-line react-hooks/exhaustive-deps

    if (!tool) {
        return <div className="text-muted">Tool &quot;{toolName}&quot; not found</div>
    }

    const properties = (tool.input_schema?.properties ?? {}) as Record<string, JsonSchemaProperty>
    const required = (tool.input_schema?.required ?? []) as string[]

    const handleSubmit = (): void => {
        clearToolResult(toolName)
        invokeTool(toolName, formValues)
    }

    return (
        <div className="space-y-4">
            <div className="space-y-3">
                {Object.entries(properties).map(([fieldName, property]) => (
                    <div key={fieldName}>
                        <LemonLabel>
                            {fieldName}
                            {required.includes(fieldName) ? <span className="text-danger ml-0.5">*</span> : null}
                        </LemonLabel>
                        {property.description ? (
                            <p className="text-muted text-xs mt-0.5 mb-1">{property.description}</p>
                        ) : null}
                        <FieldInput
                            name={fieldName}
                            property={property}
                            value={formValues[fieldName]}
                            onChange={(value) => setFormValues((prev) => ({ ...prev, [fieldName]: value }))}
                        />
                    </div>
                ))}
            </div>

            <LemonButton
                type="primary"
                onClick={handleSubmit}
                loading={isLoading}
                disabledReason={isLoading ? 'Tool is executing...' : undefined}
                fullWidth
                center
            >
                Run {toolName}
            </LemonButton>

            {result ? (
                <div
                    className={`p-3 rounded border ${
                        result.success ? 'bg-success-highlight border-success' : 'bg-danger-highlight border-danger'
                    }`}
                >
                    <pre className="whitespace-pre-wrap text-sm m-0 overflow-auto max-h-80">{result.content}</pre>
                </div>
            ) : null}
        </div>
    )
}
