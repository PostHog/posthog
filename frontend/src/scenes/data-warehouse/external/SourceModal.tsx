import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonModalProps, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { Field } from 'lib/forms/Field'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import hubspotLogo from 'public/hubspot-logo.svg'
import stripeLogo from 'public/stripe-logo.svg'

import { ExternalDataSourceType } from '~/types'

import { DatawarehouseTableForm } from '../new_table/DataWarehouseTableForm'
import {  sourceFormLogic } from './sourceFormLogic'
import { SOURCE_DETAILS, SourceConfig } from './sourceModalLogic'
import { sourceModalLogic } from './sourceModalLogic'

interface SourceModalProps extends LemonModalProps { }

export default function SourceModal(props: SourceModalProps): JSX.Element {
    const { tableLoading, selectedConnector, connectors, addToHubspotButtonUrl, modalTitle, modalCaption } =
        useValues(sourceModalLogic)
    const { selectConnector, toggleManualLinkFormVisible, onClear, onBack, onForward } = useActions(sourceModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const MenuButton = (config: SourceConfig): JSX.Element => {
        const onClick = (): void => {
            selectConnector(config)
            onForward()
        }

        if (config.name === 'Stripe') {
            return (
                <LemonButton onClick={onClick} className="w-100" center type="secondary">
                    <img src={stripeLogo} alt="stripe logo" height={50} />
                </LemonButton>
            )
        }
        if (config.name === 'Hubspot' && featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_HUBSPOT_IMPORT]) {
            return (
                <Link to={addToHubspotButtonUrl() || ''}>
                    <LemonButton className="w-100" center type="secondary">
                        <img src={hubspotLogo} alt="hubspot logo" height={45} />
                    </LemonButton>
                </Link>
            )
        }

        if (config.name === 'Postgres') {
            return (
                <LemonButton onClick={onClick} className="w-100" center type="secondary">
                    Postgres
                </LemonButton>
            )
        }

        return <></>
    }

    const onManualLinkClick = (): void => {
        toggleManualLinkFormVisible(true)
        onForward()
    }

    return (
        <LemonModal
            {...props}
            onAfterClose={() => onClear()}
            title={modalTitle}
            description={modalCaption}
        >
            <ModalPage page={1}>
                <div className="flex flex-col gap-2">
                    {connectors.map((config, index) => (
                        <MenuButton key={config.name + '_' + index} {...config} />
                    ))}
                    <LemonButton onClick={onManualLinkClick} className="w-100" center type="secondary">
                        Manual Link
                    </LemonButton>
                </div>
            </ModalPage>
            <ModalPage page={2}>
                {selectedConnector ? <SourceForm sourceType={selectedConnector.name} /> :
                    <div>
                        <DatawarehouseTableForm
                            footer={
                                <>
                                    <LemonDivider className="mt-4" />
                                    <div className="mt-2 flex flex-row justify-end gap-2">
                                        <LemonButton
                                            type="secondary"
                                            center
                                            data-attr="source-modal-back-button"
                                            onClick={onBack}
                                        >
                                            Back
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            center
                                            htmlType="submit"
                                            data-attr="source-link"
                                            loading={tableLoading}
                                        >
                                            Link
                                        </LemonButton>
                                    </div>
                                </>
                            }
                        />
                    </div>
                }
            </ModalPage>
            <ModalPage page={3}>
                <div className="flex flex-col gap-2">
                    <div className="text-lg font-bold">Linking...</div>
                </div>
            </ModalPage>
        </LemonModal>
    )
}

interface ModalPageProps {
    page: number
    children?: React.ReactNode
}

function ModalPage({ children, page }: ModalPageProps) {
    const { currentStep } = useValues(sourceModalLogic)

    if (currentStep !== page) {
        return <></>
    }

    return (
        <div>
            {children}
        </div>
    )
}

interface SourceFormProps {
    sourceType: ExternalDataSourceType
}

function SourceForm({ sourceType }: SourceFormProps): JSX.Element {
    const logic = sourceFormLogic({ sourceType })
    const { isExternalDataSourceSubmitting } = useValues(logic)
    const { onCancel } = useActions(logic)
    const { onForward } = useActions(sourceModalLogic)

    return (
        <Form
            logic={sourceFormLogic}
            props={{ sourceType }}
            formKey={sourceType == 'Postgres' ? "databaseSchema" :  "externalDataSource"}
            className="space-y-4"
            enableFormOnSubmit
        >
            {SOURCE_DETAILS[sourceType].fields.map((field) => (
                <Field key={field.name} name={['payload', field.name]} label={field.label}>
                    <LemonInput className="ph-ignore-input" data-attr={field.name} />
                </Field>
            ))}
            <Field name="prefix" label="Table Prefix (optional)">
                <LemonInput className="ph-ignore-input" data-attr="prefix" placeholder="internal_" />
            </Field>
            <LemonDivider className="mt-4" />
            <div className="mt-2 flex flex-row justify-end gap-2">
                <LemonButton type="secondary" center data-attr="source-modal-back-button" onClick={onCancel}>
                    Back
                </LemonButton>
                <LemonButton
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="source-link"
                    loading={isExternalDataSourceSubmitting}
                >
                    Link
                </LemonButton>
            </div>
        </Form>
    )
}
