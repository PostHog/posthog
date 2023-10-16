import { LemonButton, LemonInput, LemonModal, LemonModalProps } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { CONNECTORS, ConnectorConfigType, sourceModalLogic } from './sourceModalLogic'
import { useActions, useValues } from 'kea'
import { DatawarehouseTableForm } from '../DataWarehouseTable'
import { Field } from 'lib/forms/Field'
import stripeLogo from 'public/stripe-logo.svg'

interface SourceModalProps extends LemonModalProps {}

export default function SourceModal(props: SourceModalProps): JSX.Element {
    const { isAirbyteResourceSubmitting, selectedConnector, isManualLinkFormVisible, showFooter } =
        useValues(sourceModalLogic)
    const { selectConnector, toggleManualLinkFormVisible } = useActions(sourceModalLogic)

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
    }

    const onManualLinkClick = (): void => {
        toggleManualLinkFormVisible(true)
    }

    const formToShow = (): JSX.Element => {
        if (selectedConnector) {
            return (
                <Form logic={sourceModalLogic} formKey={'airbyteResource'} className="space-y-4" enableFormOnSubmit>
                    <Field name="account_id" label="Account Id">
                        <LemonInput className="ph-ignore-input" autoFocus data-attr="account-id" placeholder="acct_" />
                    </Field>
                    <Field name="client_secret" label="Client Secret">
                        <LemonInput
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="client-secret"
                            placeholder="sklive"
                        />
                    </Field>
                </Form>
            )
        }

        if (isManualLinkFormVisible) {
            return <DatawarehouseTableForm />
        }

        return (
            <div className="flex flex-col gap-2">
                {CONNECTORS.map((config, index) => (
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
            description="One click link a data source"
            footer={
                showFooter ? (
                    <div className="flex flex-row gap-2">
                        <LemonButton type="secondary" center data-attr="source-modal-back-button" onClick={onClear}>
                            Back
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            center
                            htmlType="submit"
                            data-attr="source-link"
                            loading={isAirbyteResourceSubmitting}
                        >
                            Link
                        </LemonButton>
                    </div>
                ) : null
            }
        >
            {formToShow()}
        </LemonModal>
    )
}
