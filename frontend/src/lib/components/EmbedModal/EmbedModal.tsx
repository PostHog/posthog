import { LemonModal } from 'lib/components/LemonModal'
import React from 'react'
import { InsightShortId } from '~/types'
import { useValues } from 'kea'
import { embedModalLogic } from 'lib/components/EmbedModal/embedModalLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export interface ExportModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId: InsightShortId
}

export function EmbedModal({ visible, closeModal, insightShortId }: ExportModalProps): JSX.Element {
    const { embedCode } = useValues(embedModalLogic({ insightShortId }))

    return (
        <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
            <VerticalForm logic={embedModalLogic} props={{ insightShortId }} formKey="embedConfig">
                <Field name={'width'} label={'Width'}>
                    <LemonInput />
                </Field>
                <Field name={'height'} label={'Height'}>
                    <LemonInput />
                </Field>
                <Field name={'whitelabel'}>
                    {({ value, onChange }) => (
                        <LemonCheckbox
                            id="continuity-checkbox"
                            label={<div>Whitelabel</div>}
                            onChange={() => onChange(!value)}
                            rowProps={{ fullWidth: true }}
                            checked={value}
                        />
                    )}
                </Field>
                <CodeSnippet wrap={true} language={Language.HTML}>
                    {embedCode}
                </CodeSnippet>
                <div dangerouslySetInnerHTML={{ __html: embedCode }} />
            </VerticalForm>
        </LemonModal>
    )
}
