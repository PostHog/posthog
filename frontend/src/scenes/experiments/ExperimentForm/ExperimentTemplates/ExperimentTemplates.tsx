import { useActions } from 'kea'

import { ExperimentTemplateCard } from './ExperimentTemplateCard'
import { ExperimentTemplateModal } from './ExperimentTemplateModal'
import { EXPERIMENT_TEMPLATES } from './constants'
import { experimentTemplateModalLogic } from './experimentTemplateModalLogic'

export const ExperimentTemplates = (): JSX.Element => {
    const { openTemplateModal } = useActions(experimentTemplateModalLogic)

    return (
        <>
            <div className="space-y-4">
                <div>
                    <h3 className="font-semibold text-base mb-1">Start with a template</h3>
                    <p className="text-sm text-muted">
                        Choose a pre-configured experiment template to quickly set up your metrics
                    </p>
                </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {EXPERIMENT_TEMPLATES.map((template) => (
                    <ExperimentTemplateCard key={template.id} template={template} onSelect={openTemplateModal} />
                ))}
            </div>
            <ExperimentTemplateModal onApply={() => {}} />
        </>
    )
}
