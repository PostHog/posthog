import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { kea, path } from 'kea'
import { Form, forms } from 'kea-forms'
import { z } from 'zod'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { standardSchemaToKeaErrors } from './standardSchema'

const SCHEMA_SOURCE = `z.object({
    repository: z.object({
        fullName: z.string().trim().min(1, 'Repository name is required'),
        baselinePaths: z.record(
            z.string().trim().min(1, 'Run type is required'),
            z.string().trim().min(1, 'Path is required')
        ),
    }),
})`

const WIRING_SOURCE = `// 1. Define your Zod schema
const schema = z.object({ ... })

// 2. In your kea logic, wire it into forms()
forms(() => ({
    myForm: {
        defaults: { ... },

        // Validate → returns kea-compatible error map
        errors: (values) =>
            standardSchemaToKeaErrors(schema, values),

        // Submit → parse first, get typed output
        submit: async (values) => {
            const parsed = parseWithStandardSchema(schema, values)
            if (!parsed.success) { return }
            // parsed.data is fully typed + transformed
            await api.save(parsed.data)
        },
    },
}))

// 3. In your component, use <Form> + <LemonField> as normal
<Form logic={myLogic} formKey="myForm" enableFormOnSubmit>
    <LemonField name="repository.fullName" label="Name">
        <LemonInput />
    </LemonField>
</Form>`

interface StandardSchemaStoryFormValues {
    repository: {
        fullName: string
        baselinePaths: Record<string, string>
    }
}

const standardSchemaStorySchema = z.object({
    repository: z.object({
        fullName: z.string().trim().min(1, 'Repository name is required'),
        baselinePaths: z.record(
            z.string().trim().min(1, 'Run type is required'),
            z.string().trim().min(1, 'Path is required')
        ),
    }),
})

const standardSchemaStoryLogic = kea([
    path(['lib', 'forms', 'standardSchema', 'stories']),
    forms(() => ({
        standardSchemaStoryForm: {
            defaults: {
                repository: {
                    fullName: '',
                    baselinePaths: {
                        storybook: '',
                    },
                },
            } as StandardSchemaStoryFormValues,
            errors: (values) => standardSchemaToKeaErrors(standardSchemaStorySchema, values),
            submit: async () => {
                // no-op for demo
            },
        },
    })),
])

function CodeBlock({ code, title }: { code: string; title: string }): JSX.Element {
    return (
        <div>
            <div className="text-xs font-semibold text-muted mb-1">{title}</div>
            <pre className="text-xs bg-bg-3000 rounded p-3 overflow-x-auto font-mono whitespace-pre leading-relaxed">
                {code.trim()}
            </pre>
        </div>
    )
}

function LiveErrorInspector(): JSX.Element {
    const { standardSchemaStoryFormErrors, standardSchemaStoryFormTouched } = useValues(standardSchemaStoryLogic)

    return (
        <div>
            <div className="text-xs font-semibold text-muted mb-1">Live kea-forms error state</div>
            <pre className="text-xs bg-bg-3000 rounded p-3 overflow-x-auto font-mono whitespace-pre leading-relaxed">
                {JSON.stringify(
                    {
                        errors: standardSchemaStoryFormErrors,
                        touched: standardSchemaStoryFormTouched,
                    },
                    null,
                    2
                )}
            </pre>
        </div>
    )
}

const meta: Meta = {
    title: 'Forms/Standard Schema Adapter',
    parameters: {
        docs: {
            description: {
                component: `
The Standard Schema adapter bridges any schema library that implements the
[Standard Schema](https://github.com/standard-schema/standard-schema) spec
(Zod, Valibot, ArkType) into kea-forms.

**Two helpers:**

- \`standardSchemaToKeaErrors(schema, values)\` — validates and returns a kea-compatible \`DeepPartialMap\` error object. Use in the \`errors\` callback.
- \`parseWithStandardSchema(schema, values)\` — validates and returns either \`{ success: true, data }\` with the parsed + transformed output, or \`{ success: false, errors }\`. Use in \`submit\` to get typed, coerced values (e.g. trimmed strings).

**Benefits over manual validation:**

- Schema is the single source of truth for both validation and data transformation
- Zod schemas can extend the generated API schemas from \`api.zod.ts\`
- Error paths (nested objects, arrays, records) are mapped automatically
`,
            },
        },
    },
}

export default meta

type Story = StoryObj

export const ZodShowcase: Story = {
    render: () => {
        return (
            <div className="flex gap-6 items-start max-w-4xl">
                <div className="flex-1 min-w-0 space-y-4">
                    <Form logic={standardSchemaStoryLogic} formKey="standardSchemaStoryForm" enableFormOnSubmit>
                        <div className="space-y-4">
                            <LemonField name="repository.fullName" label="Repository full name">
                                <LemonInput placeholder="posthog/posthog" />
                            </LemonField>

                            <LemonField name="repository.baselinePaths.storybook" label="Storybook baseline file path">
                                <LemonInput placeholder=".storybook/snapshots.yml" />
                            </LemonField>

                            <div className="flex justify-end">
                                <LemonButton type="primary" htmlType="submit">
                                    Validate
                                </LemonButton>
                            </div>
                        </div>
                    </Form>

                    <LiveErrorInspector />
                </div>

                <div className="flex-1 min-w-0 space-y-4">
                    <CodeBlock title="Zod schema" code={SCHEMA_SOURCE} />
                    <CodeBlock title="How to wire into kea-forms" code={WIRING_SOURCE} />
                </div>
            </div>
        )
    },
}
