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
import { SOURCE_DETAILS, sourceFormLogic } from './sourceFormLogic'
import { ConnectorConfigType, sourceModalLogic } from './sourceModalLogic'

interface SourceModalProps extends LemonModalProps {}

export default function SourceModal(props: SourceModalProps): JSX.Element {
    const { tableLoading, selectedConnector, isManualLinkFormVisible, connectors, addToHubspotButtonUrl } =
        useValues(sourceModalLogic)
    const { selectConnector, toggleManualLinkFormVisible, onClear } = useActions(sourceModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const MenuButton = (config: ConnectorConfigType): JSX.Element => {
        const onClick = (): void => {
            selectConnector(config)
        }

        if (config.name === 'Stripe') {
            return (
                <LemonButton onClick={onClick} className="w-100" center type="secondary">
                    <img src={stripeLogo} alt={`stripe logo`} height={50} />
                </LemonButton>
            )
        }
        if (config.name === 'Hubspot' && featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_HUBSPOT_IMPORT]) {
            return (
                <Link to={addToHubspotButtonUrl() || ''}>
                    <LemonButton className="w-100" center type="secondary">
                        <img src={hubspotLogo} alt={`hubspot logo`} height={45} />
                    </LemonButton>
                </Link>
            )
        }

        return <></>
    }

    const onManualLinkClick = (): void => {
        toggleManualLinkFormVisible(true)
    }

    const formToShow = (): JSX.Element => {
        if (selectedConnector) {
            return <SourceForm sourceType={selectedConnector.name} />
        }

        if (isManualLinkFormVisible) {
            return (
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
                                        onClick={onClear}
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
            )
        }

        return (
            <div className="flex flex-col gap-2">
                {connectors.map((config, index) => (
                    <MenuButton key={config.name + '_' + index} {...config} />
                ))}
                <LemonButton onClick={onManualLinkClick} className="w-100" center type="secondary">
                    Manual Link
                </LemonButton>
            </div>
        )
    }

    return (
        <LemonModal
            {...props}
            onAfterClose={() => onClear()}
            title="Data Sources"
            description={selectedConnector ? selectedConnector.caption : null}
        >
            {formToShow()}
        </LemonModal>
    )
}

interface SourceFormProps {
    sourceType: ExternalDataSourceType
}

function SourceForm({ sourceType }: SourceFormProps): JSX.Element {
    const logic = sourceFormLogic({ sourceType })
    const { isExternalDataSourceSubmitting } = useValues(logic)
    const { onBack } = useActions(logic)

    return (
        <Form
            logic={sourceFormLogic}
            props={{ sourceType }}
            formKey={'externalDataSource'}
            className="space-y-4"
            enableFormOnSubmit
        >
            <Field name="prefix" label="Table Prefix">
                <LemonInput className="ph-ignore-input" autoFocus data-attr="prefix" placeholder="internal_" />
            </Field>
            {SOURCE_DETAILS[sourceType].fields.map((field) => (
                <Field key={field.name} name={['payload', field.name]} label={field.label}>
                    <LemonInput className="ph-ignore-input" data-attr={field.name} />
                </Field>
            ))}
            <LemonDivider className="mt-4" />
            <div className="mt-2 flex flex-row justify-end gap-2">
                <LemonButton type="secondary" center data-attr="source-modal-back-button" onClick={onBack}>
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
