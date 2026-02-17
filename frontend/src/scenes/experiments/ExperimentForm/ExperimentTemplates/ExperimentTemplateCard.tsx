import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { ExperimentTemplate } from './constants'

type ExperimentTemplateCardProps = {
    template: ExperimentTemplate
    onSelect: (template: ExperimentTemplate) => void
}

export const ExperimentTemplateCard = ({ template, onSelect }: ExperimentTemplateCardProps): JSX.Element => {
    return (
        <button
            className="relative flex flex-col bg-bg-light border border-border rounded-lg hover:border-primary-3000-hover focus:border-primary-3000-hover focus:outline-none transition-colors text-left h-full group p-4 cursor-pointer"
            data-attr="experiment-template-card"
            onClick={() => onSelect(template)}
        >
            <div className="flex items-start gap-3 mb-3">
                <div className="flex-shrink-0">{template.icon}</div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-base mb-1">{template.name}</h3>
                    <p className="text-sm text-muted">{template.description}</p>
                </div>
            </div>

            <div className="mt-auto pt-2 border-t">
                <div className="flex items-center gap-2">
                    <LemonTag size="small" type="success">
                        {template.metrics.length} metrics
                    </LemonTag>
                    {template.metrics.map((metric) => (
                        <span className="text-xs text-muted truncate">{metric.name}</span>
                    ))}
                </div>
            </div>
        </button>
    )
}
