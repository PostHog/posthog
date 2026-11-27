import { QuillVariableOption } from './QuillVariableOptionsCombobox'

/** The options a list variable's query returned, with a label column when any label differs from its value. */
export function QuillVariableOptionsPreview({ options }: { options: QuillVariableOption[] }): JSX.Element {
    const hasCustomLabels = options.some((option) => option.label !== option.value)

    return (
        <ul translate="no" className="m-0 max-h-40 list-none overflow-y-auto rounded-md border border-border p-0">
            {hasCustomLabels && (
                <li className="sticky top-0 flex gap-2 border-b border-border bg-background px-2 py-1 text-xs font-medium text-muted-foreground">
                    <span className="min-w-0 flex-1">Value</span>
                    <span className="min-w-0 flex-1">Label</span>
                </li>
            )}
            {options.map((option) => (
                <li key={option.value} className="flex gap-2 border-b border-border px-2 py-1 text-xs last:border-b-0">
                    <span className="min-w-0 flex-1 truncate">{option.value}</span>
                    {hasCustomLabels && (
                        <span className="min-w-0 flex-1 truncate text-muted-foreground">{option.label}</span>
                    )}
                </li>
            ))}
        </ul>
    )
}
