import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { platformAlertLogic } from './platformAlertLogic'
import { RuleMetadataField } from './RuleMetadataField'

export function PlatformAlertRuleMetadataModal(): JSX.Element {
    const { ruleMetadataModalOpen, isRuleMetadataFormSubmitting } = useValues(platformAlertLogic)
    const { closeRuleMetadataModal, submitRuleMetadataForm } = useActions(platformAlertLogic)

    return (
        <LemonModal
            isOpen={ruleMetadataModalOpen}
            onClose={closeRuleMetadataModal}
            title="Edit labels and annotations"
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeRuleMetadataModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRuleMetadataForm}
                        loading={isRuleMetadataFormSubmitting}
                        data-attr="platform-alert-rule-metadata-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={platformAlertLogic}
                formKey="ruleMetadataForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="labels" label="Labels">
                    <RuleMetadataField kind="label" />
                </LemonField>
                <LemonField
                    name="annotations"
                    label="Annotations"
                    help={
                        <>
                            Values can use <code>{'{{ $labels.<name> }}'}</code> for a grouping key or label, and{' '}
                            <code>{'{{ $value }}'}</code> for the checked value. A name that ends in <code>_url</code>{' '}
                            needs a link that starts with https://.
                        </>
                    }
                >
                    <RuleMetadataField kind="annotation" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
