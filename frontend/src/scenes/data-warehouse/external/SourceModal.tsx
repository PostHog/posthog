import { LemonButton, LemonModal, LemonModalProps, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import hubspotLogo from 'public/hubspot-logo.svg'
import stripeLogo from 'public/stripe-logo.svg'

import { DatawarehouseTableForm } from '../new_table/DataWarehouseTableForm'
import PostgresSchemaForm from './forms/PostgresSchemaForm'
import SourceForm from './forms/SourceForm'
import { SourceConfig } from './sourceModalLogic'
import { sourceModalLogic } from './sourceModalLogic'

interface SourceModalProps extends LemonModalProps {}

export default function SourceModal(props: SourceModalProps): JSX.Element {
    const { modalTitle, modalCaption } = useValues(sourceModalLogic)
    const { onClear, onBack, onSubmit } = useActions(sourceModalLogic)
    const { currentStep } = useValues(sourceModalLogic)

    const footer = (): JSX.Element | null => {
        if (currentStep === 1) {
            return null
        }

        return (
            <div className="mt-2 flex flex-row justify-end gap-2">
                <LemonButton type="secondary" center data-attr="source-modal-back-button" onClick={onBack}>
                    Back
                </LemonButton>
                <LemonButton type="primary" center onClick={() => onSubmit()} data-attr="source-link">
                    Link
                </LemonButton>
            </div>
        )
    }

    return (
        <LemonModal
            {...props}
            width={600}
            onAfterClose={() => onClear()}
            title={modalTitle}
            description={modalCaption}
            footer={footer()}
        >
            <FirstStep />
            <SecondStep />
            <ThirdStep />
        </LemonModal>
    )
}

interface ModalPageProps {
    page: number
    children?: React.ReactNode
}

function ModalPage({ children, page }: ModalPageProps): JSX.Element {
    const { currentStep } = useValues(sourceModalLogic)

    if (currentStep !== page) {
        return <></>
    }

    return <div>{children}</div>
}

function FirstStep(): JSX.Element {
    const { connectors, addToHubspotButtonUrl } = useValues(sourceModalLogic)
    const { selectConnector, toggleManualLinkFormVisible, onNext } = useActions(sourceModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const MenuButton = (config: SourceConfig): JSX.Element => {
        const onClick = (): void => {
            selectConnector(config)
            onNext()
        }

        if (config.name === 'Stripe') {
            return (
                <LemonButton onClick={onClick} className="w-full" center type="secondary">
                    <img src={stripeLogo} alt="stripe logo" height={50} />
                </LemonButton>
            )
        }
        if (config.name === 'Hubspot') {
            return (
                <div className="w-full">
                    <Link to={addToHubspotButtonUrl() || ''}>
                        <LemonButton className="w-full" center type="secondary">
                            <img src={hubspotLogo} alt="hubspot logo" height={45} />
                        </LemonButton>
                    </Link>
                </div>
            )
        }

        if (config.name === 'Postgres' && featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_POSTGRES_IMPORT]) {
            return (
                <LemonButton onClick={onClick} className="w-full" center type="secondary">
                    Postgres
                </LemonButton>
            )
        }

        return <></>
    }

    const onManualLinkClick = (): void => {
        toggleManualLinkFormVisible(true)
        onNext()
    }

    return (
        <ModalPage page={1}>
            <div className="flex flex-col gap-2 items-center">
                {connectors.map((config, index) => (
                    <MenuButton key={config.name + '_' + index} {...config} />
                ))}
                <LemonButton onClick={onManualLinkClick} className="w-full" center type="secondary">
                    Manual Link
                </LemonButton>
            </div>
        </ModalPage>
    )
}

function SecondStep(): JSX.Element {
    const { selectedConnector } = useValues(sourceModalLogic)

    return (
        <ModalPage page={2}>
            {selectedConnector ? <SourceForm sourceType={selectedConnector.name} /> : <DatawarehouseTableForm />}
        </ModalPage>
    )
}

function ThirdStep(): JSX.Element {
    return (
        <ModalPage page={3}>
            <PostgresSchemaForm />
        </ModalPage>
    )
}
