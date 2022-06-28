import './EmbedModal.scss'
import { LemonModal } from 'lib/components/LemonModal'
import React from 'react'
import { InsightShortId } from '~/types'
import { useValues } from 'kea'
import { embedModalLogic } from 'lib/components/EmbedModal/embedModalLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export interface ExportModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId: InsightShortId
}

export function EmbedModal({ visible, closeModal, insightShortId }: ExportModalProps): JSX.Element {
    const { embedCode, iframeProperties } = useValues(embedModalLogic({ insightShortId }))

    return (
        <LemonModal
            title="Embed Insight"
            className="EmbedModal"
            onCancel={closeModal}
            afterClose={closeModal}
            visible={visible}
            width={650}
        >
            <div className="EmbedModal-split">
                <CodeSnippet wrap={true} language={Language.HTML}>
                    {embedCode}
                </CodeSnippet>
                <VerticalForm
                    logic={embedModalLogic}
                    props={{ insightShortId }}
                    formKey="embedConfig"
                    className="EmbedModal-form"
                >
                    <Field name="whitelabel" noStyle>
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                label={<div>Show Logo</div>}
                                onChange={() => onChange(!value)}
                                rowProps={{ fullWidth: true }}
                                checked={!value}
                            />
                        )}
                    </Field>
                    <Field name="noLegend" noStyle>
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                label={<div>Show Legend</div>}
                                onChange={() => onChange(!value)}
                                rowProps={{ fullWidth: true }}
                                checked={!value}
                            />
                        )}
                    </Field>
                </VerticalForm>
            </div>
            <div className="EmbedModal-preview">
                <iframe {...iframeProperties} />
            </div>
        </LemonModal>
    )
}
