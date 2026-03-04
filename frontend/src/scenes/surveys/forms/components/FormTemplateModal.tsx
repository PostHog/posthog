import { LemonModal } from '@posthog/lemon-ui'

import { FORM_TEMPLATES, FormTemplate } from '../formTemplates'
import { FormTemplatePicker } from './FormTemplatePicker'

interface FormTemplateModalProps {
    visible: boolean
    onClose: () => void
    onSelect: (template: FormTemplate) => void
}

export function FormTemplateModal({ visible, onClose, onSelect }: FormTemplateModalProps): JSX.Element {
    return (
        <LemonModal title="Choose a template" isOpen={visible} onClose={onClose} width={640}>
            <FormTemplatePicker
                templates={FORM_TEMPLATES}
                onSelect={(template) => {
                    onSelect(template)
                    onClose()
                }}
                columns={2}
            />
        </LemonModal>
    )
}
