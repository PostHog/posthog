import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonModalProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import stripeLogo from 'public/stripe-logo.svg'

import { DatawarehouseTableForm } from '../new_table/DataWarehouseTableForm'
import { ConnectorConfigType, sourceModalLogic } from './sourceModalLogic'

interface SourceModalProps extends LemonModalProps {}

export default function SourceModal(props: SourceModalProps): JSX.Element {
    const { tableLoading, isExternalDataSourceSubmitting, selectedConnector, isManualLinkFormVisible, connectors } =
        useValues(sourceModalLogic)
    const { selectConnector, toggleManualLinkFormVisible, resetExternalDataSource, resetTable } =
        useActions(sourceModalLogic)

    const MenuButton = (config: ConnectorConfigType): JSX.Element => {
        const onClick = (): void => {
            selectConnector(config)
        }

        return (
            <LemonButton onClick={onClick} className="w-100" center type="secondary">
                <img src={stripeLogo} alt={`stripe logo`} height={50} />
            </LemonButton>
        )
    }

    const onClear = (): void => {
        selectConnector(null)
        toggleManualLinkFormVisible(false)
        resetExternalDataSource()
        resetTable()
    }

    const onManualLinkClick = (): void => {
        toggleManualLinkFormVisible(true)
    }

    const formToShow = (): JSX.Element => {
        if (selectedConnector) {
            return (
                <Form logic={sourceModalLogic} formKey={'externalDataSource'} className="space-y-4" enableFormOnSubmit>
                    <Field name="prefix" label="Table Prefix">
                        <LemonInput className="ph-ignore-input" autoFocus data-attr="prefix" placeholder="internal_" />
                    </Field>
                    <Field name="account_id" label="Stripe Account ID">
                        <LemonInput className="ph-ignore-input" autoFocus data-attr="account-id" placeholder="acct_" />
                    </Field>
                    <Field name="client_secret" label="Stripe Client Secret">
                        <LemonInput
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="client-secret"
                            placeholder="sklive"
                        />
                    </Field>
                    <LemonDivider className="mt-4" />
                    <div className="mt-2 flex flex-row justify-end gap-2">
                        <LemonButton type="secondary" center data-attr="source-modal-back-button" onClick={onClear}>
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
