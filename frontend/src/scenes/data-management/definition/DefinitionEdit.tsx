import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { DefinitionLogicProps, DefinitionPageMode } from 'scenes/data-management/definition/definitionLogic'
import { useActions, useValues } from 'kea'
import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Divider } from 'antd'
import { VerticalForm } from 'lib/forms/VerticalForm'

export function DefinitionEdit(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionEditLogic(props)
    const { definitionLoading } = useValues(logic)
    const { setPageMode, saveDefinition } = useActions(logic)

    const buttons = (
        <>
            <LemonButton
                data-attr="cancel-definition"
                type="secondary"
                onClick={() => {
                    setPageMode(DefinitionPageMode.View)
                }}
                style={{ marginRight: 8 }}
                disabled={definitionLoading}
            >
                Cancel
            </LemonButton>
            <LemonButton
                data-attr="save-definition"
                type="primary"
                onClick={() => {
                    saveDefinition({})
                }}
                style={{ marginRight: 8 }}
                disabled={definitionLoading}
            >
                Save
            </LemonButton>
        </>
    )

    return (
        <VerticalForm logic={definitionEditLogic} props={props} formKey="definition">
            <PageHeader title="Edit event" buttons={buttons} />
            <Divider />
            <Divider />
            <div className="definition-footer-buttons">{buttons}</div>
        </VerticalForm>
    )
}
