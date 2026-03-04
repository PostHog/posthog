import { FormTemplate } from '../formTemplates'

interface FormTemplatePickerProps {
    templates: FormTemplate[]
    onSelect: (template: FormTemplate) => void
    columns?: 2 | 3 | 4
}

export function FormTemplatePicker({ templates, onSelect, columns = 2 }: FormTemplatePickerProps): JSX.Element {
    return (
        <div className={`grid gap-2 grid-cols-${columns}`}>
            {templates.map((template) => (
                <button
                    key={template.id}
                    type="button"
                    className="flex items-start gap-3 p-3 rounded-lg border border-border bg-bg-light hover:border-primary hover:bg-primary-highlight text-left transition-colors cursor-pointer"
                    onClick={() => onSelect(template)}
                >
                    <span className="text-muted mt-0.5 shrink-0">{template.icon}</span>
                    <div className="flex flex-col min-w-0">
                        <span className="font-medium text-sm text-default">{template.name}</span>
                        <span className="text-xs text-muted truncate">{template.description}</span>
                    </div>
                </button>
            ))}
        </div>
    )
}
