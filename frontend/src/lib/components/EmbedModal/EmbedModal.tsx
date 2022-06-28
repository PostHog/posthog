import './EmbedModal.scss'
import { LemonModal } from 'lib/components/LemonModal'
import React from 'react'
import { AvailableFeature, InsightModel, InsightShortId, InsightType } from '~/types'
import { useValues } from 'kea'
import { embedModalLogic } from 'lib/components/EmbedModal/embedModalLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { userLogic } from 'scenes/userLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { IconLock } from 'lib/components/icons'

export interface ExportModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId: InsightShortId
    insight?: Partial<InsightModel>
}

export function EmbedModal({ visible, closeModal, insightShortId, insight }: ExportModalProps): JSX.Element {
    const { embedCode, iframeProperties } = useValues(embedModalLogic({ insightShortId }))
    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []

    const disableWhitelabel = !availableFeatures.includes(AvailableFeature.WHITE_LABELLING)
    const showNoLabelCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const name = insight?.name || insight?.derived_name

    return (
        <LemonModal
            title={name ? `Embed Insight "${name}"` : 'Embed Insight'}
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
                                label={
                                    <>
                                        <span className="mr-05">Show Logo</span>
                                        {disableWhitelabel ? (
                                            <Tooltip title="Upgrade to an enterprise plan to hide the logo">
                                                <IconLock />
                                            </Tooltip>
                                        ) : null}
                                    </>
                                }
                                onChange={() => onChange(!value)}
                                rowProps={{ fullWidth: true }}
                                checked={!value}
                                disabled={disableWhitelabel}
                            />
                        )}
                    </Field>
                    {showNoLabelCheckbox && (
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
                    )}
                </VerticalForm>
            </div>
            <div className="EmbedModal-preview">
                <iframe {...iframeProperties} />
            </div>
        </LemonModal>
    )
}
